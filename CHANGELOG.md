# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-05-01

First public release on PyPI.

### Added
- Semantic edge-label prefixes (`call:`, `data:`, `event:`, `state:`, `step:`,
  `verify:`, `owns:`, `depends:`, `risk:`, `note:`) render as colored chips
  on arrows and tint the edge.
- Triple-quoted note blocks for multi-line text and notes containing quote
  characters; serializer auto-promotes single-line notes that contain quotes.
- Code-mode notes recognise system-design keywords: `call`, `await`, `emit`,
  `try`, `catch`, `state`, `assert`, `pre`, `post`, `verify`, `risk`.
- Documentation site scaffold (MkDocs Material) at
  <https://grafli.mistergc.dev>.

### Changed
- F1 help dialog: tab renamed *Notes* → *Text Annotations*, with new sections
  for edge labels and block text.
- Build system migrated to Hatchling with `hatch-vcs` for git-tag-driven
  versioning.

[Unreleased]: https://github.com/MisterGC/grafli/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/MisterGC/grafli/releases/tag/v0.1.0
