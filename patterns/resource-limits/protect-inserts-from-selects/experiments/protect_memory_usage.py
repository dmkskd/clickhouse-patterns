"""Run read/write traffic under server-enforced workload memory limits."""
from protect_writes import main

if __name__ == '__main__':
    main(policy_kind='memory-usage')
