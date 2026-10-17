#!/bin/bash
cd /mnt/d/AgentPrograms/wechat-bot
python3 -m unittest test_send_binding.BindingTests.test_group_send_uses_task_not_default_direct 2>&1 | tail -30
