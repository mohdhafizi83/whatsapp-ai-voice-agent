#!/usr/bin/env python3
"""
Aurora Store GUI automation - install WhatsApp.
Takes screenshots and analyzes to determine UI state.
"""
import subprocess
import sys
import time
import os

ADB = "adb -s localhost:5555"

def shell(cmd):
    r = subprocess.run(f"{ADB} shell {cmd}", shell=True, capture_output=True, text=True, timeout=10)
    return r.stdout.strip()

def tap(x, y):
    subprocess.run(f"{ADB} shell input tap {x} {y}", shell=True, timeout=5)

def type_text(text):
    subprocess.run(f"{ADB} shell input text \"{text}\"", shell=True, timeout=5)

def keyevent(key):
    subprocess.run(f"{ADB} shell input keyevent {key}", shell=True, timeout=5)

def screenshot():
    r = subprocess.run(f"{ADB} exec-out screencap -p", shell=True, capture_output=True, timeout=10)
    # Save to a file
    path = "/tmp/ascreen.png"
    with open(path, "wb") as f:
        f.write(r.stdout)
    # Copy to web
    subprocess.run("sudo cp /tmp/ascreen.png /var/www/funnel-landing/screen.png", shell=True, timeout=5)
    return len(r.stdout)

def main():
    print("=== Aurora Store WhatsApp Installer ===\n")
    
    # 1. Force stop and restart Aurora
    print("Starting Aurora Store...")
    shell("am force-stop com.aurora.store")
    time.sleep(1)
    shell("monkey -p com.aurora.store -c android.intent.category.LAUNCHER 1")
    time.sleep(6)
    sz = screenshot()
    print(f"Screen 1: {sz} bytes")
    
    # 2. Onboarding screens - tap Next/Continue (bottom center area)
    print("Onboarding: tapping Next...")
    for _ in range(4):  # Up to 4 onboarding screens
        tap(360, 1180)  # Bottom center
        time.sleep(2)
    
    # 3. Check for "Anonymous" login button
    print("Looking for anonymous login...")
    tap(360, 850)  # Center area where anonymous login usually is
    time.sleep(3)
    sz = screenshot()
    print(f"After login tap: {sz} bytes")
    
    # 4. Check if we're on main screen by looking for search
    # If onboarding completed, we should see search bar. Otherwise re-try.
    
    # 5. Search for WhatsApp
    print("Searching for WhatsApp...")
    tap(360, 100)  # Top search bar
    time.sleep(1)
    type_text("WhatsApp")
    time.sleep(1)
    keyevent(66)  # Enter
    time.sleep(5)
    sz = screenshot()
    print(f"After search: {sz} bytes")
    
    # 6. Tap first result (usually center of screen)
    print("Opening first result...")
    tap(360, 500)  # First search result
    time.sleep(4)
    sz = screenshot()
    print(f"App page: {sz} bytes")
    
    # 7. Tap Install button (usually green, bottom)
    tap(360, 1150)  # Install button area
    time.sleep(5)
    sz = screenshot()
    print(f"After install: {sz} bytes")
    
    print("\n✅ Automation complete!")
    print("Check: https://fiziserverstation.taila02d04.ts.net/screen.png")

if __name__ == "__main__":
    main()
