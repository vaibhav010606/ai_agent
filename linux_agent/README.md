# Linux Automation Assistant

This project implements a conversational AI agent that translates natural language instructions into real Linux shell commands and executes them on the system. The user simply describes what they want (e.g., "create a file called notes.txt in my home folder"), and the agent handles the underlying Linux commands autonomously.

## Project Structure (Separation of Concerns)

- `main.py`: The main agent loop and CLI interface. Sets up the LangChain ReAct agent.
- `tools.py`: Contains the tool definitions (e.g., the command executor and safety checker).
- `config.py`: Stores the system prompt and configuration (e.g., banned commands for safety).
- `memory.py`: Manages conversation history so the agent remembers past instructions.

## Installation

1. Create a virtual environment and install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2. Create a `.env` file in the project root and add your Groq API Key:
   ```env
   GROQ_API_KEYS=your_first_key_here,your_second_key_here
   ```
3. Run the agent:
   ```bash
   python main.py
   ```

## Core Concepts & Architecture

### 1. The ReAct Pattern
The agent uses the ReAct (Reasoning and Acting) framework. Before taking any action, the agent explicitly reasons about what to do, takes an action, and observes the result. This forms a loop that allows the agent to handle complex, multi-step tasks.

**Example Trace (Multi-Step Task):**
*User: "Install curl if it's not already installed."*
```text
Thought: Do I need to use a tool? Yes
Action: execute_linux_command
Action Input: which curl
Observation: /usr/bin/curl
Thought: Do I need to use a tool? No
Final Answer: curl is already installed on your system at /usr/bin/curl.
```

### 2. Tool Use
The agent has access to specific Python functions wrapped as LangChain tools:
- **Command Executor**: Uses Python's `subprocess` to run shell commands and capture both `stdout` and `stderr`.
- **Safety Checker**: Runs internally before `subprocess` to ensure the command doesn't match known dangerous patterns.

### 3. Prompt Engineering
The system prompt in `config.py` acts as the LLM's brain. It instructs the agent to:
- Translate plain English into valid Linux commands.
- Prioritize safe approaches.
- Read command outputs to diagnose failures.
- Summarize the final result to the user in plain English.

### 4. Memory and Context
Using `ConversationBufferMemory`, the agent retains the full conversation history. This allows for multi-turn interactions where context is implicit.

**Example of Memory in Action:**
*User: "Create a directory called my_test_dir"*
*Agent: [Executes `mkdir my_test_dir`]* "I have created the directory 'my_test_dir'."
*User: "Now put a file called hello.txt inside it"*
*Agent: [Executes `touch my_test_dir/hello.txt`]* "I have created 'hello.txt' inside 'my_test_dir'."
*(The agent knew which directory to use because of the conversation memory).*

### 5. Safety and Guardrails
Because the agent executes real commands, safety is paramount:
- A predefined list of banned patterns (e.g., `rm -rf /`, `shutdown`, `chown -R root:root /`) is enforced in `tools.py`.
- If the LLM generates a banned command, the safety checker intercepts it, blocks execution, and returns a "SAFETY VIOLATION" string to the LLM. The LLM can then re-evaluate and inform the user.

### 6. Error Handling
When a command fails (e.g., trying to read a file that doesn't exist), the system doesn't crash. Instead, `subprocess.run` captures the non-zero exit code and the `stderr` output. This is fed back to the LLM as an observation. The LLM reads the error, diagnoses the problem, and either tries a different command or explains the error to the user intelligently.

## Limitations
- **No GUI Support**: The agent cannot handle commands that open Graphical User Interfaces.
- **Async/Long-running Commands**: Extremely long downloads or interactive commands (like `nano` or `top`) are not supported natively by this synchronous loop.
- **Platform Specifics**: Works best on Linux (specifically Debian/Ubuntu variants for package management with `apt`). 
- **LLM Hallucinations**: Sometimes the LLM might hallucinate a command flag. The human user should always review the intent of the conversation.
