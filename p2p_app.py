
import socket
import threading
import struct
import os
import time


MAX_SEQUENCE_NUMBER = 65535
MAX_FRAGMENT_SIZE = 600 #TODO cant go above
#TODO upravit protokol podla bodov v hodnoteni
#TODO Pozor na veľkosť poľa "sequence number" / "poradové číslo fragmentu". V požiadavkách máte, že musíte vedieť preniesť 2MB súbor. Keď nastavím veľmi malú veľkosť fragmentu, tak môžete mať povedzme aj 100 000 fragmentov. A také číslo sa vam do 2-bajtového poľa nezmestí. Rátajte s najmenšou veľkosťou fragmentu 1 bajt, pri testovaní zadania môžeme použiť aj túto hodnotu a musí sa vám súbor korektne poslať
#TODO zistit ako sa robi ethernetove spojenie
#TODO close connection
#TODO keep-alive
#TODO pri /disconnect sa zrusi spojenie
#TODO arq
#TODO add packet corruption

# global ACTIVE = True
# global SEQENCE_NUMBER = 1

def initiateOrAnswerHandshake(peer_socket, dest_ip, dest_port):
    # Initial SYN Packet
    while not ACTIVE:
        syn_packet = Packet(ack_num=0, seq_num=SEQENCE_NUMBER, total_fragments=1, ack=0, syn=1, fin=0, err=0, sfs=0, lfg=0, ftr=0, data="")
        peer_socket.sendto(syn_packet, (dest_ip, dest_port))
        print("Sent SYN, waiting for SYN-ACK or incoming SYN...")

        try:
            peer_socket.settimeout(5)
            packet, addr = peer_socket.recvfrom(1024)
            decoded_packet = Packet(packet)

            # Check if incoming is SYN-ACK for the initiated SYN
            if decoded_packet['syn'] == 1 and decoded_packet['ack'] == 1:
                print("Received SYN-ACK, sending final ACK.")
                ack_packet = Packet(ack_num=decoded_packet['seq_num']+1, seq_num=SEQENCE_NUMBER, total_fragments=1, ack=1, syn=0, fin=0, err=0,sfs=0, lfg=0, ftr=0, data="")
                peer_socket.sendto(ack_packet, (dest_ip, dest_port))
                ACTIVE = True
                print("Handshake complete, connection established.")
                
            # Handle incoming SYN packet if both peers initiate
            elif decoded_packet['syn'] == 1 and decoded_packet['ack'] == 0:
                print("Received SYN, responding with SYN-ACK.")
                syn_ack_packet = Packet(ack_num=decoded_packet['seq_num']+1, seq_num=SEQENCE_NUMBER, total_fragments=1, ack=1, syn=1, fin=0, err=0,sfs=0, lfg=0, ftr=0, data="")
                peer_socket.sendto(syn_ack_packet, addr)

        except ConnectionResetError:
            continue


class Peer:
    def __init__(self, ip, port, dest_ip, dest_port, protocol):
        self.ip = ip
        self.port = port
        self.dest_ip = dest_ip
        self.dest_port = dest_port
        self.protocol = protocol

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((self.ip, self.port))
        self.active = True
        self.file_transfer = FileTransfer(protocol)
        self.file_receiver = FileReceiver()

    def start(self):
        threading.Thread(target=self.receiveMessages).start()
        threading.Thread(target=self.sendMessages).start()

    def sendPacket(self, dest_ip, dest_port, packet):
        self.socket.sendto(packet.toBytes(), (dest_ip, dest_port))

    def receiveMessages(self):
        while self.active:
            try:
                data, addr = self.socket.recvfrom(1024)
                packet = Packet.fromBytes(data)
                self.handlePacket(packet, addr)

                if self.file_receiver.file_complete:
                    self.file_receiver = FileReceiver()
            except Exception as e:
                print(f"Error: {e}")
            except TimeoutError:
                continue 

    def sendMessages(self):
        #TODO break the function
        while self.active:
            message = input("\n")

            # Handle fragment size change
            if message.startswith("/setfragsize "):
                try:
                    new_size = int(message.split()[1])
                    if self.protocol.setFragmentSize(new_size):
                        print(f"Fragment size set to {new_size} bytes.")
                        #TODO add sfs packet receiving
                        ack_packet = Packet(ack=1, sfs=1, data=f"Fragment size set to {new_size}")
                        self.sendPacket(self.dest_ip, self.dest_port, ack_packet)
                    else:
                        print(f"Invalid fragment size. Must be between 1 and {MAX_FRAGMENT_SIZE} bytes.")
                except ValueError:
                    print("Invalid command. Usage: /setfragsize <size>")

            # /send #TODO add to documentation
            if message.startswith("/send "):
                file_path = message[6:].strip()
                try:
                    if not os.path.exists(file_path):
                        print("Error: File does not exist.")
                        continue

                    print(f"Sending file: {file_path}")
                    self.file_transfer.sendFile(self, self.dest_ip, self.dest_port, file_path)
                except Exception as e:
                    print(f"Error sending file: {e}")
            else:
                # Regular text message
                packet = Packet(ack=1, data=message)
                self.socket.sendto(packet.toBytes(), (self.dest_ip, self.dest_port))

                if message == "/disconnect":
                    self.active = False

    def handlePacket(self, packet, addr):
        if packet.ftr == 1:  # File transfer packet
            #print(f"Receiving file fragment {packet.seq_num}")
            self.file_receiver.receiveFragment(packet)
        else:
            print(f"\n{addr[0]}:{addr[1]} >> {packet.data}")


class Protocol:
    def __init__(self, frag_size=MAX_FRAGMENT_SIZE):
        self.frag_size = frag_size

    def setFragmentSize(self, size):
        if size < 1 or size > MAX_FRAGMENT_SIZE:
            return False
        self.frag_size = size
        return True

    def fragmentData(self, data):
        #TODO add explanation of setting frag size with /setfragsize N, sfs-ack, sfs-err packets; lfg is 1 if
        fragments = [data[i:i + self.frag_size] for i in range(0, len(data), self.frag_size)]
        return fragments


class Packet:
    def __init__(self, ack_num=0, seq_num=0, ack=0, syn=0, fin=0, err=0, sfs=0, lfg=0, ftr=0, checksum=0, data_length=0, data=""):
        self.ack_num = ack_num
        self.seq_num = seq_num
        self.ack = ack
        self.syn = syn
        self.fin = fin
        self.err = err
        self.sfs = sfs
        self.lfg = lfg
        self.ftr = ftr
        self.checksum = checksum
        self.data_length = data_length
        self.data = data

    def toBytes(self):
        flags = (self.ack << 7) | (self.syn << 6) | (self.fin << 5) | (self.err << 4) | (self.sfs << 3) | (self.lfg << 2) | (self.ftr << 1)
        checksum = self.calculateChecksum(self.data.encode('utf-8'))
        header = struct.pack(
            '!HHBHH',
            self.ack_num,          # 16b
            self.seq_num,          # 16b #TODO update documentation: removed fragment num
            flags,                 # 8b
            checksum,              # 16b
            len(self.data)         # 16b
        )
        return header + self.data.encode('utf-8')

    @staticmethod
    def fromBytes(packet):
        #TODO Update documentation (changes): removed total_fragments field, added LFG (last fragment) flag, added SFS (set fragment size) flag, added FTR (file transfer) flag;
        header = packet[:9]
        ack_num, seq_num, flags, checksum, data_length = struct.unpack('!HHBHH', header)
        data = packet[9:].decode('utf-8')

        return Packet(
            ack_num=ack_num,
            seq_num=seq_num,
            ack=(flags >> 7) & 1,
            syn=(flags >> 6) & 1,
            fin=(flags >> 5) & 1,
            err=(flags >> 4) & 1,
            sfs=(flags >> 3) & 1,
            lfg=(flags >> 2) & 1,
            ftr=(flags >> 1) & 1,
            checksum=checksum,
            data_length=data_length,
            data=data
        )

    @staticmethod
    def calculateChecksum(data):
        polynomial = 0x8005
        crc = 0xFFFF

        for byte in data:
            crc ^= (byte << 8)
            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ polynomial
                else:
                    crc <<= 1
                crc &= 0xFFFF

        crc ^= 0xFFFF
        return crc


class FileTransfer:
    def __init__(self, protocol):
        self.protocol = protocol

    def sendFile(self, peer, dest_ip, dest_port, file_path):
        try:
            filename = os.path.basename(file_path)
            with open(file_path, 'rb') as file:
                data = file.read()
                fragments = self.protocol.fragmentData(data.decode('latin1'))
                total_fragments = len(fragments)

                # Send filename in a separate packet
                #TODO add to documentation: first packet is total_fragments (8hex digits) + '|' + filename (ftr=1, ack=1)
                setup_packet = Packet(  # Special sequence number for filename
                    ftr=1,
                    ack=1,
                    lfg=0,
                    data=f"{total_fragments:08x}|{filename}"
                )
                peer.sendPacket(dest_ip, dest_port, setup_packet)
                
                for i, fragment in enumerate(fragments):
                    packet = Packet(
                        seq_num=i + 1,
                        lfg=(1 if i == len(fragments) - 1 else 0),
                        ftr=1,
                        data=fragment
                    )
                    peer.sendPacket(dest_ip, dest_port, packet)

                    # Show progress
                    print(f"\rSent {i + 1}/{total_fragments} packets", end="", flush=True)
                
                print("\nFile sent successfully.")
                
        except FileNotFoundError:
            print("File not found.")
        except Exception as e:
            print(f"Error sending file: {e}")


class FileReceiver:
    def __init__(self):
        self.file_fragments = {}  # Stores fragments by sequence number
        self.expected_fragments = None  # Total fragments to expect
        self.file_complete = False
        self.current_filename = None  # Track the file being received

    def receiveFragment(self, packet):
        if packet.ftr != 1: # Non file fragment => ignore
            return

        # Handle filename packet
        if packet.ack == 1: 
            try:
                total_fragments_hex, filename = packet.data.split('|', 1)
                self.expected_fragments = int(total_fragments_hex, 16)
                self.current_filename = filename
                print(f"Receiving file: {filename} ({self.expected_fragments} fragments expected)")
            except ValueError:
                print("Error parsing header packet.")
            return

        else:
            self.file_fragments[packet.seq_num] = packet.data

            if self.expected_fragments:
                # Show progress
                print(f"\rReceived {len(self.file_fragments)}/{self.expected_fragments} packets", end="", flush=True)

            if self.expected_fragments and len(self.file_fragments) == self.expected_fragments:
                self.reconstructFile()
                self.file_complete = True


    def reconstructFile(self):
        save_path = input("Enter path to save the file << ")
        if not os.path.exists(save_path):
            print("Path does not exist, saving to default download directory...")
            save_path = ""
        elif save_path[-1:] not in ['\\', '/']:
            save_path += '\\'

        save_path += self.current_filename
        with open(save_path, 'wb') as f:
            for seq_num in sorted(self.file_fragments.keys()):
                f.write(self.file_fragments[seq_num].encode('latin1'))
        print(f"File successfully received and saved as \"{save_path}\".")


#! type "/disconnect" on both nodes to terminate connection

if __name__ == '__main__':
    src_ip = "127.0.0.1"
    dest_ip = "127.0.0.1"#!
    #dest_ip = input("Destination IP: ")
    dest_port = int(input("Destination Port: "))
    src_port = int(input("Listening Port: "))
    
    protocol = Protocol(frag_size=MAX_FRAGMENT_SIZE)
    peer = Peer(src_ip, src_port, dest_ip, dest_port, protocol)

    peer.start()
