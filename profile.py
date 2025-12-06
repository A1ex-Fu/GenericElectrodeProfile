import geni.portal as portal
import geni.rspec.pg as rspec

# --- CONFIGURATION ---

# Using the URL with the token you provided in the prompt
REPO_URL = "https://github.com/A1ex-Fu/vrpaxos.git"
TARGET_KERNEL_VERSION = "5.8.0-050800-generic"

# --- THE SETUP SCRIPT ---
# This script handles: Kernel Update -> Reboot -> Dependencies -> Git Clone -> Setup
SETUP_SCRIPT = r"""#!/bin/bash
set -e

# Redirect all output to log file for debugging
exec > >(tee -a /local/setup.log) 2>&1

echo "--- Setup Script Started at $(date) ---"

# 1. IDENTIFY USER
# CloudLab mounts user homes in /users/. We pick the first non-root user.
USER_NAME=$(ls /users | grep -v root | head -n 1)
USER_HOME="/users/$USER_NAME"
echo "Detected User: $USER_NAME"
echo "User Home: $USER_HOME"

# 2. CHECK KERNEL VERSION
CURRENT_KERNEL=$(uname -r)
DESIRED_KERNEL="{target_kernel}"

if [[ "$CURRENT_KERNEL" != *"$DESIRED_KERNEL"* ]]; then
    echo "Current kernel ($CURRENT_KERNEL) does not match desired ($DESIRED_KERNEL)."
    echo "Installing Kernel 5.8.0..."

    # Download and run the kernel script
    wget -N https://raw.githubusercontent.com/pimlie/ubuntu-mainline-kernel.sh/master/ubuntu-mainline-kernel.sh
    chmod +x ubuntu-mainline-kernel.sh
    sudo bash ubuntu-mainline-kernel.sh -i 5.8.0 --yes

    # Set GRUB to boot this kernel
    echo "Updating GRUB default..."
    # We grab the menu entry ID for the 5.8 kernel
    GRUB_ENTRY="Advanced options for Ubuntu>Ubuntu, with Linux $DESIRED_KERNEL"
    sudo grub-set-default "$GRUB_ENTRY"
    
    # Ensure it sticks
    sudo update-grub

    echo "Rebooting node to apply kernel..."
    # Create a marker so we know we attempted a reboot
    touch /local/kernel_rebooted
    sudo reboot
    
    # Script stops here due to reboot
    exit 0
fi

echo "Kernel is correct: $CURRENT_KERNEL"

# 3. INSTALL DEPENDENCIES (Run as Root)
if [ ! -f /local/dependencies_installed ]; then
    echo "Installing Dependencies..."
    export DEBIAN_FRONTEND=noninteractive
    sudo apt-get update
    sudo apt-get install -y llvm clang gpg curl tar xz-utils make gcc flex bison \
        libssl-dev libelf-dev protobuf-compiler pkg-config libunwind-dev \
        libssl-dev libprotobuf-dev libevent-dev libgtest-dev

    touch /local/dependencies_installed
else
    echo "Dependencies already installed."
fi

# 4. CLONE REPO & PREP (Run as User)
REPO_DIR="$USER_HOME/vrpaxos"

if [ ! -d "$REPO_DIR" ]; then
    echo "Cloning Repository into $REPO_DIR..."
    
    # IMPORTANT: Run git as the user, not root!
    sudo -u $USER_NAME git clone {repo_url} $REPO_DIR
    
    echo "Running Kernel Prep Scripts..."
    cd $REPO_DIR
    
    # Run the prep scripts as the user so permissions stay correct
    if [ -f kernel-src-download.sh ]; then
        echo "Running kernel-src-download.sh..."
        sudo -u $USER_NAME bash kernel-src-download.sh
    fi
    
    if [ -f kernel-src-prepare.sh ]; then
        echo "Running kernel-src-prepare.sh..."
        sudo -u $USER_NAME bash kernel-src-prepare.sh
    fi

    echo "Repository Setup Complete."
else
    echo "Repository directory already exists at $REPO_DIR"
fi

echo "--- Setup Driver Finished Successfully at $(date) ---"
""".format(target_kernel=TARGET_KERNEL_VERSION, repo_url=REPO_URL)


# --- GENILIB DEFINITION ---

pc = portal.Context()
request = pc.makeRequestRSpec()

# Standard Ubuntu Image
IMAGE = 'urn:publicid:IDN+emulab.net+image+emulab-ops//UBUNTU20-64-STD'

# Define LAN
lan = request.LAN("lan")
lan.bandwidth = 25600000 

NUM_NODES = 4

for i in range(NUM_NODES):
    node = request.RawPC("node-{}".format(i+1))
    node.disk_image = IMAGE
    
    # Networking
    iface = node.addInterface("if1")
    iface.addAddress(rspec.IPv4Address("10.10.1.{}".format(i+1), "255.255.255.0"))
    lan.addInterface(iface)

    # --- SETUP SERVICE ---
    # We write the script to /local/startup.sh and run it on every boot
    # The script itself handles the logic of "do I need to reboot?" or "am I done?"
    
    cmd_write = "cat << 'EOF' > /local/startup.sh\n{}\nEOF".format(SETUP_SCRIPT)
    cmd_chmod = "chmod +x /local/startup.sh"
    # Run immediately in background
    cmd_run   = "nohup /local/startup.sh &" 
    
    # Add to rc.local or crontab to ensure it runs after the reboot
    cmd_persist = "(crontab -l 2>/dev/null; echo '@reboot /local/startup.sh') | crontab -"

    full_cmd = "{} && {} && {} && {}".format(cmd_write, cmd_chmod, cmd_persist, cmd_run)

    node.addService(rspec.Execute(shell="bash", command=full_cmd))

pc.printRequestRSpec(request)