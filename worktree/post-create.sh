#!/bin/bash

for item in web/node_modules web/.env.local .env .venv; do
  ln -sfn /Users/roy/luohy15/code/y-agent/$item $item
done
