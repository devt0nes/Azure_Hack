#!/bin/sh
# Clean dev-only lint dependencies before Docker build to avoid npm ci conflicts
cp package.json package.json.bak
jq 'del(.devDependencies["eslint"]) | del(.devDependencies["eslint-plugin-react-hooks"]) | del(.devDependencies["eslint-plugin-react-refresh"]) | del(.devDependencies["@eslint/js"])' package.json.bak > package.json
