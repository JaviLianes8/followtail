# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0]

- First release.
- `follow(path, *, poll, from_start, encoding, max_idle, sleep)`: iterate new complete
  lines from a growing text file, surviving rotation by rename and recreate or truncate.
