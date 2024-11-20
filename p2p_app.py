
import socket
import threading
import struct
import os
import time


MAX_SEQUENCE_NUMBER = 65535
MAX_FRAGMENT_SIZE = 600 #TODO cant go above
#TODO Pozor na veľkosť poľa "sequence number" / "poradové číslo fragmentu". V požiadavkách máte, že musíte vedieť preniesť 2MB súbor. Keď nastavím veľmi malú veľkosť fragmentu, tak môžete mať povedzme aj 100 000 fragmentov. A také číslo sa vam do 2-bajtového poľa nezmestí. Rátajte s najmenšou veľkosťou fragmentu 1 bajt, pri testovaní zadania môžeme použiť aj túto hodnotu a musí sa vám súbor korektne poslať

#TODO zistit ako sa robi ethernetove spojenie
#TODO finish protocol
#TODO upravit protokol podla bodov v hodnoteni

#TODO close connection
#TODO pri /disconnect sa zrusi spojenie
#TODO arq
#TODO add packet corruption

class Peer:
    def __init__(self, ip, port, dest_ip, dest_port, protocol):
        self.ip = ip
        self.port = port
        self.dest_ip = dest_ip
        self.dest_port = dest_port
        self.protocol = protocol
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((self.ip, self.port))
        
        self.active = False
        self.handshake_complete = False 
        self.file_transfer = FileTransfer(protocol)
        self.file_receiver = FileReceiver()

        # Keep-alive and reconnection
        self.keep_alive_interval = 5
        self.ping_timeout = 3
        self.last_ping_time = 0
        self.reconnect_attempts = 0

        self.fin_sent = False
        self.connection_terminated = False
        self.expected_fin_ack_seq = -1

        self.message_seq_num = 1 #txt and heartbeat packets

    def start(self):
        threading.Thread(target=self.receiveMessages).start()
        threading.Thread(target=self.handleInput).start()
        threading.Thread(target=self.keepAlive).start()
        self.initiateHandshake()

    def initiateHandshake(self):
        print("Attempting handshake...")
        while not self.handshake_complete:
            try:
                self.handshake()    
            except ConnectionResetError:
                continue

    def handshake(self):
        #TODO include handshake initialization to documentation if needed
        if not self.active:
            syn_packet = Packet(ack_num=0, seq_num=1, syn=1, ack=0, fin=0)
            self.socket.sendto(syn_packet.toBytes(), (self.dest_ip, self.dest_port))
            #print("Sent SYN packet.")
            try:
                self.socket.settimeout(5)
                data, addr = self.socket.recvfrom(1024)
                packet = Packet.fromBytes(data)

                if packet.syn == 1 and packet.ack == 1:
                    print("Received SYN-ACK, sending final ACK.")
                    ack_packet = Packet(ack_num=packet.seq_num + 1, seq_num=0, ack=1, syn=0, fin=0)
                    self.socket.sendto(ack_packet.toBytes(), (self.dest_ip, self.dest_port))
                    self.handshake_complete = True
                    self.active = True
                    print("Handshake complete, connection established.")
                elif packet.syn == 1:
                    print("Received SYN, sending SYN-ACK.")
                    syn_ack_packet = Packet(ack_num=0, seq_num=1, syn=1, ack=1, fin=0)
                    self.socket.sendto(syn_ack_packet.toBytes(), addr)     
            except socket.timeout:
                pass
        else:
            self.socket.settimeout(None)

    def keepAlive(self):
        global last_heartbeat_ack
        missed_heartbeats = 0

        while not self.active:
            continue
        while self.active:
            last_heartbeat_ack = False

            heartbeat_packet = Packet(ack=1, seq_num=0)
            self.sendPacket(self.dest_ip, self.dest_port, heartbeat_packet)
            # print("Heartbeat sent.")

            time.sleep(self.keep_alive_interval)

            if not last_heartbeat_ack:
                missed_heartbeats += 1
                print(f"Missed {missed_heartbeats} heartbeat(s).")
            else:
                missed_heartbeats = 0

            if missed_heartbeats >= self.ping_timeout:
                break
            
        self.handleConnectionLost()

    def sendHeartbeat(self):
        #print("Sending heartbeat packet...")#!DEBUG
        packet = Packet(ack=1, seq_num=0)
        self.sendPacket(self.dest_ip, self.dest_port, packet)
        self.last_heartbeat_time = time.time()  # Timestamp of the heartbeat sent
        self.heartbeat_retries += 1  # Increment retry count

    def handleConnectionLost(self):
        #TODO add handle disconnection to documentation: tries to reconnect again with handshake, keeps file transfer info; but only reconnects if the connection wasnt manually terminated
        if not self.connection_terminated:
            print("Connection lost.")
            self.active = False
            self.handshake_complete = False 
            self.socket.close()
            self.__init__(self.ip, self.port, self.dest_ip, self.dest_port, self.protocol)
            self.start()

        # If the transfer was interrupted, resume the transfer here
        # if self.file_transfer.in_progress:
        #     self.file_transfer.resumeTransfer(self) #TODO
            
    def sendPacket(self, dest_ip, dest_port, packet):
        packet.ack_num = self.file_receiver.next_expected_seq
        self.socket.sendto(packet.toBytes(), (dest_ip, dest_port))

    def receiveMessages(self):
        while not self.active:
            continue
        while self.active:
            try:
                data, addr = self.socket.recvfrom(1024)
                packet = Packet.fromBytes(data)
                self.handlePacket(packet, addr)
            except socket.timeout:
                time.sleep(1) 
            except Exception as e:
                #print(f"Error: {e}")
                time.sleep(1)

    def handlePacket(self, packet, addr): #TODO!
        global last_heartbeat_ack
        
        if packet.fin == 1:
            print("FIN received from peer.")
            ack_packet = Packet(ack=1, seq_num=packet.seq_num)
            self.sendPacket(self.dest_ip, self.dest_port, ack_packet)
            self.active = False
            self.connection_terminated = True
            self.socket.close()
            print("Connection terminated successfully.")

           
        elif packet.ack == 1 and self.fin_sent: #TODO check ack
            print("ACK received for my FIN.")
            self.active = False
            self.connection_terminated = True
            self.socket.close()
            print("Connection terminated successfully.")

        elif packet.seq_num == 0 and packet.ack == 1 and packet.syn == 0:  # Heartbeat packet
            # print("Heartbeat received") #!DEBUG
            last_heartbeat_ack = True

        elif packet.seq_num > 0:  # Data packet
            #if packet.seq_num == self.file_receiver.next_expected_seq: #TODO
                if packet.ftr == 1:  # File transfer packet
                    self.file_receiver.receiveFragment(packet)
                    self.file_receiver.next_expected_seq += 1

                    if self.file_receiver.file_complete:
                        self.file_receiver = FileReceiver()
                    
                else:
                    print(f"\n{addr[0]}:{addr[1]} >> {packet.data}")

                
            #else:
                #TODO handle out of order packet
                #print(f"Out-of-order packet received: {packet.seq_num}, expected {self.file_receiver.next_expected_seq}")     

    def handleInput(self):
        while not self.active: continue
        while self.active:
            user_input = input("\n")
            if not self.active: break

            if user_input.startswith("/setfragsize "):
                try:
                    new_size = int(user_input.split()[1])
                    self.setFragmentSize(new_size)
                except ValueError:
                    print("Invalid command. Usage: /setfragsize <size>")
            #TODO add commands to documentation
            elif user_input.startswith("/send "):
                file_path = user_input[6:].strip()
                self.sendFile(file_path)
            elif user_input.startswith("/disconnect"):
                self.trerminateConnection()
            else:
                self.sendTextMessage(user_input)

    def sendFile(self, file_path):
        #TODO DOCUMENTATION: ftr packets have their own ack_num 
        try:
            if os.path.exists(file_path):
                print(f"Sending file: {file_path}")
                self.file_transfer.sendFile(self, self.dest_ip, self.dest_port, file_path)
            else:
                print("Error: File does not exist.")
        except Exception as e:
            print(f"Error sending file: {e}")   

    def sendTextMessage(self, message):
        self.message_seq_num = (self.message_seq_num + 1) % (MAX_SEQUENCE_NUMBER + 1)
        if self.message_seq_num == 0: 
            self.message_seq_num = 1

        packet = Packet(seq_num=self.message_seq_num, data=message)
        self.socket.sendto(packet.toBytes(), (self.dest_ip, self.dest_port))
        self.message_seq_num += 1

    def setFragmentSize(self, new_size):
        if self.protocol.setFragmentSize(new_size):
            print(f"Fragment size set to {new_size} bytes.")
            #TODO add sfs packet receiving to documentation
            ack_packet = Packet(ack=1, sfs=1, data=f"Fragment size set to {new_size}")
            self.sendPacket(self.dest_ip, self.dest_port, ack_packet)
        else:
            print(f"Invalid fragment size. Must be between 1 and {MAX_FRAGMENT_SIZE} bytes.")

    def trerminateConnection(self): #TODO DOCUMENTATION: update to 2-way disconnect handshake (fin, ack)
        self.message_seq_num = (self.message_seq_num + 1) % (MAX_SEQUENCE_NUMBER + 1)
        if self.message_seq_num == 0: 
            self.message_seq_num = 1

        fin_packet = Packet(fin=1, seq_num=self.message_seq_num)
        self.sendPacket(self.dest_ip, self.dest_port, fin_packet)
        self.fin_sent = True
        print("FIN packet sent.")
 

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
    #TODO DOCUMENTATION: ack_num should reset with every file; the files have their own ack_num and messages too
    def __init__(self, protocol):
        self.protocol = protocol

    def sendFile(self, peer, dest_ip, dest_port, file_path):
        self.file_seq_num = 1

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

                    # Wait for acknowledgment
                    #TODO! ARQ
                    try:
                        peer.socket.settimeout(5)
                        ack_data, _ = peer.socket.recvfrom(1024)
                        ack_packet = Packet.fromBytes(ack_data)
                        if ack_packet.ack == 1 and ack_packet.ack_num == packet.seq_num + 1:
                            print(f"Acknowledgment received for packet {packet.seq_num}")
                            break
                    except socket.timeout:
                        print(f"Timeout waiting for acknowledgment of packet {packet.seq_num}, retransmitting...")

                    # Show progress
                    print(f"\rSent {i + 1}/{total_fragments} packets", end="", flush=True)

                    self.file_seq_num += 1#TODO fully implement

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
        self.next_expected_seq = 1

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


if __name__ == '__main__':
    src_ip = "127.0.0.1"
    dest_ip = "127.0.0.1"#!
    #dest_ip = input("Destination IP: ")
    dest_port = int(input("Destination Port: "))
    src_port = int(input("Listening Port: "))
        
    protocol = Protocol(frag_size=MAX_FRAGMENT_SIZE)
    peer = Peer(src_ip, src_port, dest_ip, dest_port, protocol)

    peer.start()
