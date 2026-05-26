# Project: Fibonacci Tree Visualizer

## Goal
Develop a Python-based CLI tool that generates and visualizes fractal tree structures using ASCII/Unicode characters in the terminal, based on the Fibonacci sequence.

## Tech Stack
- **Language:** Python 3.x (Standard Library only)
- **Rendering:** Terminal-based ASCII/Unicode

## Requirements
1. **Dynamic Growth**: Ability to adjust the number of iterations (depth) and the golden ratio scaling factor via command-line arguments or interactive prompts.
2. **Terminal Visualization**: The tree must be rendered using ASCII or Unicode characters within the CLI.
3. **Mathematical Accuracy**: The branching structure must strictly adhere to Fibonacci-based logic.
4. **Configuration**: Support for customizing branch angles and thickness (line weight) via CLI flags.

## Acceptance Criteria
1. Users can successfully render a tree in the terminal without performance issues.
2. The terminal output accurately reflects the input mathematical parameters.
3. The tool runs seamlessly in any standard command-line interface (CMD/Bash/Zsh).

## Required Planning Constraint
Smith must create exactly 4 sequential tasks and no extra phases unless the project is blocked.

## Required Plan
## Overview
Develop a Python-based CLI tool to generate and visualize Fibonacci-based fractal tree structures using ASCII/Unicode in the terminal.

## Phases
1. **T001: Core Fibonacci Logic & Tree Generation Engine**
   - Implement mathematical logic for Fibonacci branching.
   - Create a function to generate the tree structure (nodes/branches) as a hyper-structure or coordinate list.
2. **T002: ASCII/Unicode Rendering Engine**
   - Implement the terminal-based rendering logic.
   - Support Unicode characters for better visual representation.
3. **T003: CLI Interface & Parameter Implementation**
   - Implement `argparse` for depth, scaling factor, angles, and thickness.
   - Support interactive prompts for easy use.
4. **T004: Testing & Final Verification**
   - Implement `unittest` suite for mathematical accuracy and rendering stability.
   - Final end-to-end validation.

## Required Outputs
- README.md
- src/main.py
- tests/test_main.py

## Determinism Rules
- Keep the task structure exactly T001, T002, T003, T004.
- Do not invent extra tasks unless blocked.
- Keep file names stable unless blocked.
- Use the normal team workflow end to end.
