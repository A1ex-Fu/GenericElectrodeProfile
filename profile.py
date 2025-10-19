# -*- coding: utf-8 -*-

# Import the necessary CloudLab libraries.
import geni.portal as portal
import geni.rspec.pg as rspec

# Create a portal context.
pc = portal.Context()

# Create a Request object to start building the RSpec.
request = pc.makeRequestRSpec()

# Define the OS Image to use. UBUNTU20-64-STD is the standard 64-bit Ubuntu 20.04 image.
IMAGE = 'urn:publicid:IDN+emulab.net+image+emulab-ops//UBUNTU20-64-STD'

# Define the number of nodes.
NUM_NODES = 4

# Create a LAN to connect all nodes.
lan = request.LAN("lan")
lan.bandwidth = 25600000  # Set bandwidth to 25 Gbps (in Kbps)

# Create the nodes and add them to the LAN.
for i in range(NUM_NODES):
    node = request.RawPC("node-{}".format(i+1))
    # node.hardware_type = 'xl170'
    node.disk_image = IMAGE

    # Add an interface to the node and connect to LAN
    iface = node.addInterface("if1")
    lan.addInterface(iface)

    # Assign roles: node-1 is the client, others are Paxos replicas
    if i == 0:
        node.addService(rspec.Execute(shell="sh", command="/local/repository/setup_client.sh"))
    else:
        node.addService(rspec.Execute(shell="sh", command="/local/repository/setup_replica.sh"))

    # Performance tuning: reserve cores and disable irqbalance
    node.addService(rspec.Execute(shell="sh", command="echo 1 > /sys/bus/workqueue/devices/writeback/cpumask"))
    node.addService(rspec.Execute(shell="sh", command="echo 2 > /sys/bus/workqueue/devices/writeback/cpumask"))
    node.addService(rspec.Execute(shell="sh", command="systemctl disable irqbalance"))

# Print the RSpec to the RSpec editor.
pc.printRequestRSpec(request)