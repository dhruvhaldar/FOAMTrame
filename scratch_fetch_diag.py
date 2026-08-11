import sys
import os
from trame.app import get_server

# Initialize a dummy trame server
server = get_server(client_type="vue2")
state = server.state

# Import and call setup_setup_tab
from tabs.setup_tab import setup_setup_tab
setup_setup_tab(server)

# Set up necessary states
state.docker_image = "haldardhruv/ubuntu_noble_openfoam:v12"
state.openfoam_version = "12"

# Import threading to wait for thread to complete
import threading
import time

print("Starting fetch...")
# Trigger fetch_tutorials
# Since trigger_fetch_tutorials starts a thread, let's wait for it to complete.
server.controller.trigger_fetch_tutorials()

# Poll state.tutorials_loaded
for i in range(20):
    time.sleep(1)
    print(f"Status: {state.setup_status} (loaded: {state.tutorials_loaded})")
    if state.tutorials_loaded:
        break

print(f"tutorials_list length: {len(state.tutorials_list)}")
print(f"filtered_tutorials length: {len(state.filtered_tutorials)}")
if state.tutorials_list:
    print("First 5 tutorials in list:")
    print(state.tutorials_list[:5])
