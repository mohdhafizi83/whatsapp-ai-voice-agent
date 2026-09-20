#!/usr/bin/env python3
"""
Direct HFP RFCOMM connection test.
Connects to phone's HFP Audio Gateway via RFCOMM channel 3.
Tests AT commands for call control.
"""
import socket
import time
import sys

PHONE_MAC = "74:38:22:47:66:C9"
RFCOMM_CHANNEL = 3

def create_rfcomm_socket():
    """Create a Bluetooth RFCOMM socket and connect to phone."""
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    sock.settimeout(10)
    print(f"Connecting to {PHONE_MAC} channel {RFCOMM_CHANNEL}...")
    try:
        sock.connect((PHONE_MAC, RFCOMM_CHANNEL))
        print("✅ RFCOMM connected!")
        return sock
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return None

def send_at(sock, cmd, wait=0.5):
    """Send AT command and read response."""
    full_cmd = f"{cmd}\r\n"
    print(f"  >> {cmd}")
    sock.send(full_cmd.encode())
    time.sleep(wait)
    response = b""
    sock.settimeout(2)
    try:
        while True:
            chunk = sock.recv(1024)
            if not chunk:
                break
            response += chunk
            if b"\r\n" in response[-10:]:
                break
    except socket.timeout:
        pass
    response_str = response.decode(errors='replace').strip()
    lines = [l.strip() for l in response_str.split('\r\n') if l.strip()]
    for line in lines:
        print(f"  << {line}")
    return lines

def main():
    print("═══════════════════════════════════")
    print("  HFP RFCOMM Direct Test")
    print("═══════════════════════════════════")
    print()
    
    sock = create_rfcomm_socket()
    if not sock:
        return
    
    try:
        # HFP Init sequence
        print("\n--- HFP Init ---")
        print()
        
        # 1. Send BRSF (Supported Features)
        features = 0b11000001  # EC/NR + Call waiting + CLI + Voice recog
        send_at(sock, f"AT+BRSF={features}")
        time.sleep(1)
        
        # 2. Query supported indicators
        send_at(sock, "AT+CIND=?")
        time.sleep(0.5)
        
        # 3. Get current indicator values
        send_at(sock, "AT+CIND?")
        time.sleep(0.5)
        
        # 4. Enable indicator events
        send_at(sock, "AT+CMER=3,0,0,1")
        time.sleep(0.5)
        
        # 5. Set speaker volume
        send_at(sock, "AT+VGS=15")
        time.sleep(0.5)
        
        # 6. Set microphone gain
        send_at(sock, "AT+VGM=15")
        time.sleep(0.5)
        
        print("\n--- Waiting for events (Ctrl+C to stop) ---")
        print("Try calling the phone now...")
        print()
        
        # Listen for incoming events (+CIEV, RING, etc.)
        sock.settimeout(60)
        try:
            while True:
                data = sock.recv(1024)
                if not data:
                    print("Connection closed by phone")
                    break
                text = data.decode(errors='replace').strip()
                for line in text.split('\r\n'):
                    line = line.strip()
                    if line:
                        ts = time.strftime('%H:%M:%S')
                        print(f"[{ts}] 📱 {line}")
                        
                        # Auto-detect RING
                        if line == "RING":
                            print("  🔊 PHONE IS RINGING!")
                        # Call setup indicator
                        if "+CIEV:" in line and "3," in line:
                            val = line.split(",")[1].strip()
                            if val == "1":
                                print("  📞 INCOMING CALL!")
                            elif val == "0":
                                print("  📴 Call ended")
                        
        except KeyboardInterrupt:
            print("\nStopped by user")
        except socket.timeout:
            print("Timeout - no events")
        except Exception as e:
            print(f"Error: {e}")
        
    finally:
        sock.close()
        print("Connection closed")

if __name__ == "__main__":
    main()
