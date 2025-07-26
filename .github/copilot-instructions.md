<!-- Use this file to provide workspace-specific custom instructions to Copilot. For more details, visit https://code.visualstudio.com/docs/copilot/copilot-customization#_use-a-githubcopilotinstructionsmd-file -->

# SimpleBot

This is a simplified Telegram bot project based on the DewBot structure. It includes only single-sided attack battle logic and character management.

## Project Structure

- The main bot code is in `src/main.py`
- Database operations are in `src/database/`
- Game logic (attack system) is in `src/game/`
- Character management is in `src/character/`

## Design Principles

- Keep the code modular and easy to understand
- Follow a clean separation of concerns
- Database operations should be isolated in the queries module
- User interaction should be handled by command handlers
