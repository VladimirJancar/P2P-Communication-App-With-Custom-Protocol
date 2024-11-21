
import socket
import threading
import struct
import os
import time

MAX_SEQUENCE_NUMBER = 65535 #TODO
MAX_FRAGMENT_SIZE = 600
FILE_TRANSFERING = False 
#TODO Pozor na veľkosť poľa "sequence number" / "poradové číslo fragmentu". V požiadavkách máte, že musíte vedieť preniesť 2MB súbor. Keď nastavím veľmi malú veľkosť fragmentu, tak môžete mať povedzme aj 100 000 fragmentov. A také číslo sa vam do 2-bajtového poľa nezmestí. Rátajte s najmenšou veľkosťou fragmentu 1 bajt, pri testovaní zadania môžeme použiť aj túto hodnotu a musí sa vám súbor korektne poslať
#TODO DOC: header sizes (32 bits?)
#TODO zistit ako sa robi ethernetove spojenie

#TODO limit max char limit for text message
#TODO arq, ukončenie spojenia po timeoute na oboch stranách
#TODO DOC: ARQ: send packets on one thread and receive acks on second one; if err packet is received, resend fragment; if fragment missing, resend
#TODO add packet corruption / checksum

#TODO DOC: disconnect diagram (3-way handshake)
#TODO lua script
#TODO DOC ukazka testovania

class Peer:
    def __init__(self, ip, port, dest_ip, dest_port, protocol):
        self.ip = ip
        self.port = port
        self.dest_ip = dest_ip
        self.dest_port = dest_port
        self.protocol = protocol
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) #UDP?
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

        self.connection_terminated = False
        self.expected_fin_ack = -1

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
            while FILE_TRANSFERING:
                continue

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
        if not self.connection_terminated:
            print("Connection lost.")
            self.active = False
            self.handshake_complete = False 
            self.socket.close()
            self.__init__(self.ip, self.port, self.dest_ip, self.dest_port, self.protocol)
            self.start()
      
    def sendPacket(self, dest_ip, dest_port, packet):
        self.socket.sendto(packet.toBytes(), (dest_ip, dest_port))

    def receiveMessages(self):
        while not self.active:
            continue
        while self.active:
            while FILE_TRANSFERING:
                continue
            try:
                data, addr = self.socket.recvfrom(1024)
                packet = Packet.fromBytes(data)
                self.handlePacket(packet, addr)
            except socket.timeout:
                time.sleep(1) 
            except Exception as e:
                #print(f"Error: {e}")
                time.sleep(1)

    def handlePacket(self, packet, addr):
        global last_heartbeat_ack
        global FILE_TRANSFERING
        
        if packet.fin == 1:
            print("FIN received from peer. Sending ACK...")
            ack_packet = Packet(ack=1, seq_num=packet.seq_num)
            self.sendPacket(self.dest_ip, self.dest_port, ack_packet)
            self.active = False
            self.connection_terminated = True
            self.socket.close()
            print("Connection terminated successfully.")
           
        elif packet.ack == 1 and self.expected_fin_ack == packet.seq_num:
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
                    print("received ftf packet")
                    FILE_TRANSFERING = True
                    self.file_receiver = FileReceiver()
                    self.file_receiver.handleFragment(packet)
                    self.file_receiver.receivePackets(self.socket)
                    # if self.file_receiver.file_complete:
                    #     self.file_receiver = FileReceiver()
                    
                else:
                    print(f"\n{addr[0]}:{addr[1]} >> {packet.data}")

        #TODO handle setfragsize
            #else:
                #TODO handle out of order packet
                #print(f"Out-of-order packet received: {packet.seq_num}, expected {self.file_receiver.next_expected_seq}")     

    def handleInput(self):
        while not self.active: continue
        while self.active:
            while FILE_TRANSFERING:
                continue

            user_input = input("\n")
            if not self.active: break

            if user_input.startswith("/setfragsize "):
                try:
                    new_size = int(user_input.split()[1])
                    self.setFragmentSize(new_size)
                except ValueError:
                    print("Invalid command. Usage: /setfragsize <size>")
            elif user_input.startswith("/send "):
                file_path = user_input[6:].strip()
                self.sendFile(file_path)
            elif user_input.startswith("/disconnect"):
                self.trerminateConnection()
            else:
                self.sendTextMessage(user_input)

    def sendFile(self, file_path):
        global FILE_TRANSFERING
        self.file_transfer = FileTransfer(protocol)
        try:
            if os.path.exists(file_path):
                FILE_TRANSFERING = True
                print(f"Sending file: {file_path}")
                self.file_transfer.sendFile(self, self.dest_ip, self.dest_port, file_path)
            else:
                print("Error: File does not exist.")
        except Exception as e:
            print(f"Error sending file: {e}")   

    def sendTextMessage(self, message):
        self.message_seq_num = (self.message_seq_num + 1)
        if self.message_seq_num == 0: 
            self.message_seq_num = 1

        packet = Packet(seq_num=self.message_seq_num, data=message)
        self.socket.sendto(packet.toBytes(), (self.dest_ip, self.dest_port))
        self.message_seq_num += 1

    def setFragmentSize(self, new_size):
        if self.protocol.setFragmentSize(new_size):
            print(f"Fragment size set to {new_size} bytes.")
            #TODO add sfs packet receiving and sending the size to set
            ack_packet = Packet(ack=1, sfs=1, data=f"Fragment size set to {new_size}")
            self.sendPacket(self.dest_ip, self.dest_port, ack_packet)
        else:
            print(f"Invalid fragment size. Must be between 1 and {MAX_FRAGMENT_SIZE} bytes.")

    def trerminateConnection(self):
        self.message_seq_num = (self.message_seq_num + 1) % (MAX_SEQUENCE_NUMBER + 1)
        if self.message_seq_num == 0: 
            self.message_seq_num = 1

        self.expected_fin_ack = self.message_seq_num
        fin_packet = Packet(fin=1, seq_num=self.message_seq_num)
        self.sendPacket(self.dest_ip, self.dest_port, fin_packet)
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
        fragments = [data[i:i + self.frag_size] for i in range(0, len(data), self.frag_size)]
        return fragments


class Packet:
    def __init__(self, ack_num=0, seq_num=0, ack=0, syn=0, fin=0, err=0, sfs=0, lfg=0, ftr=0, checksum=0, data=""):
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
        self.data = data

    def toBytes(self):
        flags = (self.ack << 7) | (self.syn << 6) | (self.fin << 5) | (self.err << 4) | (self.sfs << 3) | (self.lfg << 2) | (self.ftr << 1)
        checksum = 1#self.calculateChecksum#!(self.data.encode('utf-8'))
        header = struct.pack(
            '!IIBH',
            self.ack_num,          # 16b
            self.seq_num,          # 16b
            flags,                 # 8b
            checksum,              # 16b
        )
        return header + self.data.encode('utf-8')

    @staticmethod
    def fromBytes(packet):
        header = packet[:11]
        ack_num, seq_num, flags, checksum = struct.unpack('!IIBH', header)
        data = packet[11:].decode('utf-8')

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
    def __init__(self, protocol, timeout=2):
        self.unacknowledged_packets = {}
        self.file_seq_num = 1
        self.protocol = protocol
        self.timeout = timeout
        self.total_fragments = 0

    def sendFragments(self, peer, dest_ip, dest_port, fragments):
        for seq_num, fragment in enumerate(fragments, start=1):
            packet = Packet(
                seq_num=seq_num, 
                lfg=(1 if seq_num == self.total_fragments else 0),  # Last fragment flag
                ftr=1,
                data=fragment
            )

            self.unacknowledged_packets[seq_num] = packet

            peer.sendPacket(dest_ip, dest_port, packet)
            print(f"\rFragments > {seq_num}/{self.total_fragments} sent", end="", flush=True)

        print("\nFile sent successfully.")

    def receiveAcks(self):
        while True:
            try:
                ack_data, _ = peer.socket.recvfrom(1024)
                ack_packet = Packet.fromBytes(ack_data)

                if ack_packet.ack == 1: # ACK
                    seq_num = ack_packet.ack_num
                    if seq_num in self.unacknowledged_packets:
                        del self.unacknowledged_packets[seq_num]
                        #print(f"Fragments > {seq_num}/{self.total_fragments} acknowledged", end="", flush=True)
                
                elif ack_packet.err == 1:  # Err packet with missing seq_num
                    missing_seq = ack_packet.ack_num
                    if missing_seq in self.unacknowledged_packets:
                        packet = self.unacknowledged_packets[missing_seq]
                        peer.sendPacket(peer.dest_ip, peer.dest_port, packet)
                        print(f"Retransmitted missing packet {missing_seq}")

            except socket.timeout:
                #TODOprint(f"Timeout: Resending packet {i + 1}")
                continue
            except Exception as e:
                break

    def sendFile(self, peer, dest_ip, dest_port, file_path):
        global FILE_TRANSFERING
        try:
            filename = os.path.basename(file_path)
            with open(file_path, 'rb') as file:
                data = file.read()
                fragments = self.protocol.fragmentData(data.decode('latin1'))
                self.total_fragments = len(fragments)

                # Send setup packet with total_fragments and filename
                setup_packet = Packet(
                    seq_num=self.file_seq_num,
                    ftr=1,
                    ack=1,
                    data=f"{self.total_fragments:08x}|{filename}"
                )
                peer.sendPacket(dest_ip, dest_port, setup_packet)

                # Start sending and receiving threads
                send_thread = threading.Thread(target=self.sendFragments, args=(peer, dest_ip, dest_port, fragments))
                ack_thread = threading.Thread(target=self.receiveAcks, args=(peer))

                send_thread.start()
                ack_thread.start()

                send_thread.join()
                ack_thread.join()                   
                
        except FileNotFoundError:
            print("Error: File not found.")
        except Exception as e:
            print(f"Error sending file: {e}")
        
        FILE_TRANSFERING = False


class FileReceiver:
    def __init__(self):
        self.file_fragments = {}  # Stores fragments by sequence number
        self.expected_fragments = None  # Total fragments to expect
        self.file_complete = False
        self.current_filename = None  # Track the file being received
        self.expected_seq = 1

        self.wrap_count = 0

    def receivePackets(self, socket):        
        while FILE_TRANSFERING:
            try:
                data, addr = socket.recvfrom(1024)
                packet = Packet.fromBytes(data)
                self.handleFragment(packet)
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Error: {e}")

    def handleFragment(self, packet):
        if packet.ftr != 1:
            return

        if packet.ack == 1:  # Filename packet
            try:
                total_fragments_hex, filename = packet.data.split('|', 1)
                self.expected_fragments = int(total_fragments_hex, 16)
                self.current_filename = filename
                print(f"Receiving file: {filename} ({self.expected_fragments} fragments expected)")
            except ValueError:
                print("Error parsing header packet.")
            return

        # Handle fragment packet
        seq_num = packet.seq_num
        # if seq_num == self.expected_seq:
        self.file_fragments[seq_num] = packet.data

            # Send ACK for received packet
        ack_packet = Packet(
            ack=1,
            ack_num=seq_num
        )
        peer.sendPacket(peer.dest_ip, peer.dest_port, ack_packet)
        #print(f"ACK sent for packet {seq_num}")

        self.expected_seq += 1
        #else:
        #    print(f"Out-of-order or duplicate packet {seq_num}. Expected {self.next_expected_seq}")

        # Show progress
        if self.expected_fragments:
            print(f"\rReceived {len(self.file_fragments)}/{self.expected_fragments} packets", end="", flush=True)

        # Check if file transfer is complete
        if self.expected_fragments and len(self.file_fragments) == self.expected_fragments:
            self.reconstructFile()
            self.file_complete = True
                
    def reconstructFile(self):
        global FILE_TRANSFERING
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
        FILE_TRANSFERING = False



if __name__ == '__main__':
    src_ip = "127.0.0.1"
    dest_ip = "127.0.0.1"#!
    #dest_ip = input("Destination IP: ")
    dest_port = int(input("Destination Port: "))
    src_port = int(input("Listening Port: "))
        
    protocol = Protocol(frag_size=MAX_FRAGMENT_SIZE)
    peer = Peer(src_ip, src_port, dest_ip, dest_port, protocol)

    peer.start()
