# -*- coding: utf-8 -*-
import geni.portal as portal
import geni.rspec.pg as rspec

# --- CONFIGURATION ---

GITHUB_URL = "https://github.com/A1ex-Fu/vrpaxos.git"
DESIRED_KERNEL = "5.8.0-050800-generic"

# --- THE STATE MACHINE SCRIPT ---
# This shell script runs on every boot. It checks what needs to be done.
# We embed it here as a Python string to write it to the nodes later.
SETUP_SCRIPT = r"""#!/bin/bash
set -e # Exit on error

# Logs output to /local/setup.log for debugging
exec > >(tee -a /local/setup.log) 2>&1

ROLE=$1  # "client" or "replica" passed from profile

echo "--- Starting Setup Driver ($(date)) ---"
echo "Current Kernel: $(uname -r)"

# ==========================================================
# PHASE 1: ALWAYS RUN (Network Configuration)
# ==========================================================
# Ensure experimental interface is named 'eth1' and multicast is ON.
# This must run on every boot because /sys settings reset.

# Find interface with 10.10.1.x IP
EXP_IFACE=$(ip -o -4 addr list | grep '10.10.1' | awk '{print $2}')

if [ -n "$EXP_IFACE" ]; then
    if [ "$EXP_IFACE" != "eth1" ]; then
        echo "Renaming $EXP_IFACE to eth1..."
        sudo ip link set dev $EXP_IFACE down
        sudo ip link set dev $EXP_IFACE name eth1
        sudo ip link set dev eth1 up
        EXP_IFACE="eth1"
    fi
    echo "Enabling Multicast on $EXP_IFACE..."
    sudo ip link set dev $EXP_IFACE multicast on
    sudo ip route add 224.0.0.0/4 dev $EXP_IFACE || echo "Route exists"
else
    echo "WARNING: Could not find interface with 10.10.1.x IP"
fi

# ==========================================================
# PHASE 2: KERNEL UPDATE (Runs once)
# ==========================================================
CURRENT_KERNEL=$(uname -r)

if [[ "$CURRENT_KERNEL" != *"{target_kernel}"* ]]; then
    echo "Kernel mismatch. Installing {target_kernel}..."
    
    # Download and install kernel
    wget -N https://raw.githubusercontent.com/pimlie/ubuntu-mainline-kernel.sh/master/ubuntu-mainline-kernel.sh
    chmod +x ubuntu-mainline-kernel.sh
    # Non-interactive install
    sudo bash ubuntu-mainline-kernel.sh -i 5.8.0 --yes
    
    echo "Updating GRUB..."
    sudo grub-set-default "Ubuntu, with Linux {target_kernel}"
    
    echo "Rebooting in 5 seconds to apply kernel..."
    sleep 5
    sudo reboot
    exit 0 # Script stops here, system reboots
fi

echo "Kernel is correct."

# ==========================================================
# PHASE 3: DEPENDENCIES & REPO (Runs once after reboot)
# ==========================================================
if [ ! -f /local/setup_complete_marker ]; then
    echo "Installing Dependencies..."
    export DEBIAN_FRONTEND=noninteractive
    sudo apt update
    sudo apt install -y llvm clang gpg curl tar xz-utils make gcc flex bison \
        libssl-dev libelf-dev protobuf-compiler pkg-config libunwind-dev \
        libssl-dev libprotobuf-dev libevent-dev libgtest-dev

    echo "Cloning Repository..."
    # Remove existing dir if it exists to be safe
    rm -rf /users/$(whoami)/vrpaxos
    git clone {github_url} /users/$(whoami)/vrpaxos

    cd /users/$(whoami)/vrpaxos
    
    echo "Running Kernel Prep Scripts..."
    if [ -f kernel-src-download.sh ]; then
        bash kernel-src-download.sh
        bash kernel-src-prepare.sh
    else
        echo "Warning: kernel-src scripts not found in repo."
    fi

    # Mark this phase as done so we don't re-run apt/git on next boot
    touch /local/setup_complete_marker
else
    echo "Dependencies and Repo already setup."
fi

# ==========================================================
# PHASE 4: APPLICATION STARTUP
# ==========================================================
# Run the specific client/replica scripts provided in the repository
if [ "$ROLE" == "client" ]; then
    echo "Starting Client Setup..."
    if [ -f /local/repository/setup_client.sh ]; then
        bash /local/repository/setup_client.sh
    fi
else
    echo "Starting Replica Setup..."
    if [ -f /local/repository/setup_replica.sh ]; then
        bash /local/repository/setup_replica.sh
    fi
fi

echo "Setup Driver Finished Successfully."
""".replace("{target_kernel}", DESIRED_KERNEL).replace("{github_url}", GITHUB_URL)


pc = portal.Context()
request = pc.makeRequestRSpec()
IMAGE = 'urn:publicid:IDN+emulab.net+image+emulab-ops//UBUNTU20-64-STD'
NUM_NODES = 4

lan = request.LAN("lan")
lan.bandwidth = 25600000 

for i in range(NUM_NODES):
    node = request.RawPC("node-{}".format(i+1))
    node.disk_image = IMAGE

    # Networking
    iface = node.addInterface("if1")
    iface.addAddress(rspec.IPv4Address("10.10.1.{}".format(i+1), "255.255.255.0"))
    lan.addInterface(iface)

    # Determine Role
    role = "client" if i == 0 else "replica"

    # --- INJECTION SEQUENCE ---
    # 1. Write the script to the node
    # 2. Add it to Crontab @reboot so it survives the kernel update reboot
    # 3. Execute it manually the first time to kick off the process
    
    cmd_write = "cat << 'EOF' > /local/setup_driver.sh\n{}\nEOF".format(SETUP_SCRIPT)
    cmd_chmod = "chmod +x /local/setup_driver.sh"
    cmd_cron  = "(crontab -l 2>/dev/null; echo '@reboot /local/setup_driver.sh {}') | crontab -".format(role)
    cmd_start = "/local/setup_driver.sh {} &".format(role) # Run in background so CloudLab doesn't hang waiting

    # Chain commands into one addService to ensure order
    full_cmd = "{} && {} && {} && {}".format(cmd_write, cmd_chmod, cmd_cron, cmd_start)
    
    node.addService(rspec.Execute(shell="bash", command=full_cmd))

    # Standard tuning
    node.addService(rspec.Execute(shell="sh", command="echo 1 > /sys/bus/workqueue/devices/writeback/cpumask"))
    node.addService(rspec.Execute(shell="sh", command="systemctl disable irqbalance"))

pc.printRequestRSpec(request)