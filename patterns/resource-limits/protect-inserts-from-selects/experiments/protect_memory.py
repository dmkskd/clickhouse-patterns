"""Run the shared traffic generator with workload memory admission."""
from protect_writes import main

if __name__ == '__main__':
    main(policy_kind='memory')
