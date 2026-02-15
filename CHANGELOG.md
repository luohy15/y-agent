# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-02-15

### Added
- **Web UI**: Full React web frontend with Solarized theme, markdown rendering, and CLI-style messages
- **Serverless backend**: AWS SAM-based API (Lambda) and Celery task queue worker
- **Google OAuth authentication** for multi-user support
- **Agent package**: Autonomous tool-use loop with `LoopResult` and unified CLI/worker runners
- **Skill discovery**: Auto-detect and load agent skills
- **Remote VM execution** via Sprites API backend with configurable `VmBackend` parameter
- **Chat sharing**: Public share view with DB-backed deduplication and `/share/:shareId` route
- **Tool approval system**: Per-tool-call approval modal, auto-approve toggle, deny-with-message, and tool status display
- **Chat interrupt/stop** functionality across full stack (CLI, API, and web)
- **SQLite local storage** and D1 export command
- **Intent analyzer** for smart routing and dependency cleanup
- **One-off prompt mode** for non-interactive usage
- **Responsive mobile UI**: Hamburger menu sidebar, dvh viewport units, zoom prevention on input focus
- **Running cursor indicator** in message list during agent execution
- **User isolation**: `user_id` support in bot config for multi-user environments
- Perplexity links display support
- GitHub link icon in Header and ShareView

### Changed
- **Project renamed** to y-agent
- **Major restructure**: Multi-package workspace with `cli`, `storage`, `admin`, `api`, `agent`, and `worker` packages
- Replaced DynamoDB cache with DB-backed chat state and Celery task queue
- Consolidated API routes under `/api` prefix
- Refactored user management and service layer abstractions
- Refactored tool approval flow with separate rejected/cancelled backfill modes
- Refactored `MessageList` into shared component with improved tool display
- Improved web deployment pipeline with SWR replacing manual polling
- Auto-allow read-only bash commands for smoother agent experience
- Moved Google sign-in button from header to chat view landing page
- Made header logo clickable to start new chat

### Removed
- MCP daemon and deprecated features
- VPC config from Lambda functions (simplified networking)

## [0.4.0] - 2025-06-09

### Added
- Cloudflare D1 storage integration as a new storage_type option
- Chat import command for migrating between storage types
- Enhanced Message model with parent_id field for message relationships
- Enhanced Chat model with new fields for content tracking and message selection
- Documentation for Cloudflare D1 setup and usage

### Changed
- Replaced Cloudflare KV/R2 storage with more robust Cloudflare D1 database solution
- Updated repository factory to support D1 database
- Refactored chat service HTML generation for better TOC integration
- Improved list_chats to support more advanced filtering options

### Removed
- Cloudflare Worker backup functionality (replaced by D1's built-in reliability)
- Legacy Cloudflare KV/R2 storage implementation

## [0.3.13] - 2025-03-25

### Added
- Cloudflare storage integration for chat data with KV and R2 support
- MCP daemon for persistent MCP server connections between sessions
- Prompt configuration management system with customizable prompts
- Asynchronous repository operations for improved performance
- Repository factory pattern for flexible storage selection
- Cloudflare worker script for automated backups
- Detailed documentation for new features

### Changed
- Refactored chat repository into modular structure
- Updated chat manager to support async repository operations
- Enhanced message models with MCP tool execution information
- Improved logging with loguru integration
- Updated system architecture documentation
- Optimized display manager for tool execution representation

## [0.3.10] - 2025-02-25

### Added
- Topia Orchestration Provider support
- Memory bank documentation structure
- Project rules documentation (.clinerules)
- Immediate chat ID generation for better session management
- New utility function for ID generation

### Changed
- Updated default model from claude-3.5-sonnet to claude-3.7-sonnet
- Improved README with new features and demo visuals
- Enhanced display manager to better handle structured content
- Updated chat service to support pre-generated chat IDs

## [0.3.7] - 2025-02-13

### Changed
- Use bot name as provider if not provider info

## [0.3.6] - 2025-02-13

### Fixed
- Fixed reasoning content output

## [0.3.5] - 2025-02-13

### Fixed
- Fixed bot config print_speed

## [0.3.4] - 2025-02-13

### Fixed
- Fixed infinite recursion bug in bot configuration service when ensuring default config exists

## [0.3.3] - 2025-02-12

### Changed
- Refactored MCP server configuration system
- Renamed mcp_setting package to mcp_server for better clarity
- Simplified MCP server configuration structure

## [0.3.2] - 2025-02-11

### Added
- New visual documentation with interactive chat and multiple bot screenshots

### Changed
- Refactored ChatApp initialization to use BotConfig for better configuration management
- Improved README documentation with visual examples

## [0.3.1] - 2025-02-11

### Changed
- Modified bot configuration defaults handling for better flexibility

## [0.3.0] - 2025-02-11

### Added
- Bot configuration system
- MCP server settings integration with bot configs
- New CLI commands for managing bot configurations (`bot add`, `bot list`, `bot delete`)
- Improved chat list filtering by model and provider
- Dynamic terminal width handling for better display

### Changed
- Major project restructuring with dedicated packages for bot, chat, and CLI components
- Moved CLI components to dedicated cli package
- Updated configuration system to use bot configs
- Improved error handling and user feedback
- Enhanced system prompt with current time

## [0.2.5] - 2025-02-08

### Added
- Smooth output print with rate-limited streaming (30 chars/sec)

## [0.2.4] - 2025-02-08

### Fixed
- Fix list -k error
- Fix scrolling error using vertical_overflow="visible"

## [0.2.3] - 2025-02-06

### Added
- Support deepseek-r1 reasoning content
- Add model, provider info

## [0.2.2] - 2025-02-06

### Fixed
- Prevent saving system message

## [0.2.0] - 2025-02-06

### Added
- Add MCP client support for integrating with Model Context Protocol servers
- Add cache_control for prompt caching

## [0.1.1] - 2025-02-05

### Fixed
- Fix fcntl compatible issue

### Added
- Support copy command when chat: use 0 for entire message, 1-n for specific code blocks
- Support OpenRouter indexed db file import
