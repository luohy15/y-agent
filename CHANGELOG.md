# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
