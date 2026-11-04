#!/bin/sh
set -eu
cd "$(dirname "$0")"
mkdir -p .build
swiftc -I Sources/CSQLite Sources/TennisCore/*.swift Checks/main.swift -o .build/core-check
.build/core-check ../contracts/fixtures
