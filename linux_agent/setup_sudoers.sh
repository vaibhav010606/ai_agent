#!/bin/bash
echo "Setting up limited passwordless sudo for the Linux Agent..."
echo "This allows the agent to run 'apt update', 'apt install', and 'systemctl restart' without hanging."

# Create the sudoers rule
echo "$(whoami) ALL=(ALL) NOPASSWD: /usr/bin/apt update, /usr/bin/apt install *, /bin/systemctl restart *" | sudo tee /etc/sudoers.d/linux_agent_sudo > /dev/null

sudo chmod 440 /etc/sudoers.d/linux_agent_sudo
echo "Done! The agent can now securely update packages and restart services autonomously."
