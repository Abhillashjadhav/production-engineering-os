# Local task tracker — approved acceptance proposal

This proposal contains **14 criteria** across 6 functional requirements.
The owner confirmed the amended grid before generation. This document is
regenerated in full from publisher-input.json, scenarios.json and execution-profile.json.
The contract is produced by the existing PMOS → PEOS publisher.

## Problem

A person needs a dependable local list of tasks whose completion state survives closing and reopening the CLI.

## Target user

A single person managing tasks on one machine through a CLI.

## Desired outcome

The user can create, complete and find the intended tasks with correct durable state, without manually repairing software or stored data.

## Scope

- Local CLI: python product.py --store PATH create TITLE; complete ID; list [--status all|open|completed]. The store path is required; list defaults to all. Every command is a fresh process.
- Owner-approved IDs: positive JSON integers, starting at 1 per empty store and increasing by one on each successful create; IDs and the next ID persist across process restarts. A rejected create must not advance the next-ID counter.
- Proposed titles: reject empty or whitespace-only text, otherwise preserve exactly including Unicode and surrounding spaces.
- Owner-approved duplicates: each successful create is a new task even for an identical title. Create is not retry-idempotent. Duplicate-on-retry is approved behavior, not a defect; no create retry-safety claim.
- Owner-approved completion: existing open task becomes completed; repeating completion succeeds with the same task and no state mutation.
- Proposed JSON CLI protocol: create/complete return {task:{id,title,status}}; list returns {tasks:[...]}, ordered by ascending ID. Errors return {error:CODE}. Exit codes: 0 success, 2 invalid input or unknown ID, 1 storage failure.
- Persist acknowledgements before exit; malformed stores fail without replacement. Proposed durability covers orderly process exit and restart, not power-loss durability.
- AC-013 runs ten strictly sequential creates, each process exiting before the next starts; a new list process then checks all acknowledged records. Concurrent creation is out of scope; do not test parallel writers.

## Out of scope

- Concurrent creation and other concurrent writers; no parallel-writer tests. Deletion, editing titles, due dates, login, sync, HTTP APIs and databases.
- Deduplicating repeated creates or guaranteeing idempotent create retries after an uncertain acknowledgement.
- Crash during a write, power failure, network isolation guarantees, adversarial root containment, signing-authority repair and production-readiness claims.

## Requirements

- **FR-001 — Create tasks with stable identity:** Create a nonblank task as open, assign a persistent increasing integer ID and preserve its title. A rejected create must not advance the next-ID counter.
- **FR-002 — Complete tasks:** Complete the addressed task while preserving all other tasks.
- **FR-003 — Find tasks by status:** List all tasks or the exact open/completed subset ordered by ID.
- **FR-004 — Preserve acknowledged state across restart:** Preserve tasks, completion state and next ID across orderly process restart; do not acknowledge failed storage or overwrite malformed stores.
- **FR-005 — Reject invalid requests without state changes:** Reject invalid titles, IDs and filters with documented errors and unchanged state.
- **FR-006 — Make repeated operations predictable:** Identical titles may create distinct tasks; repeated completion is idempotent.

## Acceptance grid

Every criterion must pass; severity never permits skipping a criterion.

| ID | Scenario and expected result | Observation | Severity |
| --- | --- | --- | --- |
| AC-001 | An empty store lists zero tasks successfully. | Sequential CLI processes; exact exits and JSON | Major |
| AC-002 | Creating a nonblank title preserves its text, assigns ID 1 and status open; a fresh process reads the same task. | Sequential CLI processes; exact exits and JSON | Major |
| AC-003 | Completing task 1 changes only its status and preserves task 2. | Sequential CLI processes; exact exits and JSON | Major |
| AC-004 | Open, completed and all filters return exactly the correct partition, ordered by ID. | Sequential CLI processes; exact exits and JSON | Major |
| AC-005 | Across process restarts, completed task 1 and open task 2 persist; the next creation receives ID 3. | Sequential CLI processes; exact exits and JSON | Critical |
| AC-006 | Repeated creation of the exact same title intentionally creates two tasks with distinct persistent IDs. | Sequential CLI processes; exact exits and JSON | Major |
| AC-007 | Completing an already completed task again returns success with the same task; state and the other task remain unchanged. | Sequential CLI processes; exact exits and JSON | Major |
| AC-008 | Empty and whitespace-only titles return INVALID_TITLE with exit 2 and create no task. | Sequential CLI processes; exact exits and JSON | Major |
| AC-009 | Zero, negative and noninteger IDs return INVALID_ID; unknown positive ID 999 returns NOT_FOUND; existing state is unchanged. | Sequential CLI processes; exact exits and JSON | Major |
| AC-010 | Unsupported status done returns INVALID_STATUS with exit 2; existing state is unchanged. | Sequential CLI processes; exact exits and JSON | Major |
| AC-011 | Malformed existing storage returns STORE_INVALID with exit 1, preserves the original bytes and does not silently reset data. | Sequential CLI processes; exact exits and JSON; before/after store-byte digest | Critical |
| AC-012 | A creation that cannot persist because its store parent is a regular file returns STORE_IO with exit 1 and never acknowledges success. | Sequential CLI processes; exact exits and JSON | Critical |
| AC-013 | After ten strictly sequential creates, each process exits before the next starts. A new list process must find every acknowledged record: zero records missing. The observer counts distinct valid acknowledgements; at least ten are required. Concurrent creation is out of scope; do not test parallel writers. | Actual registered measure; count acknowledged records against a new list process | Critical |
| AC-014 | In a fresh store, reject a blank title, then create a valid task. The valid task receives ID 1 and the store contains exactly that one task. A rejected create must not advance the next-ID counter. | Sequential CLI processes; exact exits and JSON | Critical |

## Exact scenario body

Each section below is generated from the same criterion as its grid row.
Commands execute synchronously. A process exits before the next starts.

### AC-001 — Major

An empty store lists zero tasks successfully.

```json
{
  "criterion": "An empty store lists zero tasks successfully.",
  "given": [
    {
      "operator": "eq",
      "path": "acceptance.ready",
      "value": true
    }
  ],
  "id": "AC-001",
  "requirement": "FR-003",
  "severity": "major",
  "then": [
    {
      "operator": "eq",
      "path": "result.observations",
      "value": [
        {
          "exit_code": 0,
          "output": {
            "tasks": []
          }
        }
      ]
    },
    {
      "operator": "eq",
      "path": "result.setup_observations",
      "value": []
    },
    {
      "operator": "eq",
      "path": "result.process_count",
      "value": 1
    }
  ],
  "when": {
    "action": "task_tracker.observe",
    "arguments": {
      "fixture": "empty",
      "steps": [
        [
          "list"
        ]
      ]
    }
  }
}
```

### AC-002 — Major

Creating a nonblank title preserves its text, assigns ID 1 and status open; a fresh process reads the same task.

```json
{
  "criterion": "Creating a nonblank title preserves its text, assigns ID 1 and status open; a fresh process reads the same task.",
  "given": [
    {
      "operator": "eq",
      "path": "acceptance.ready",
      "value": true
    }
  ],
  "id": "AC-002",
  "requirement": "FR-001",
  "severity": "major",
  "then": [
    {
      "operator": "eq",
      "path": "result.observations",
      "value": [
        {
          "exit_code": 0,
          "output": {
            "task": {
              "id": 1,
              "status": "open",
              "title": "  Café notes  "
            }
          }
        },
        {
          "exit_code": 0,
          "output": {
            "tasks": [
              {
                "id": 1,
                "status": "open",
                "title": "  Café notes  "
              }
            ]
          }
        }
      ]
    },
    {
      "operator": "eq",
      "path": "result.setup_observations",
      "value": []
    },
    {
      "operator": "eq",
      "path": "result.process_count",
      "value": 2
    }
  ],
  "when": {
    "action": "task_tracker.observe",
    "arguments": {
      "fixture": "empty",
      "steps": [
        [
          "create",
          "  Café notes  "
        ],
        [
          "list"
        ]
      ]
    }
  }
}
```

### AC-003 — Major

Completing task 1 changes only its status and preserves task 2.

```json
{
  "criterion": "Completing task 1 changes only its status and preserves task 2.",
  "given": [
    {
      "operator": "eq",
      "path": "acceptance.ready",
      "value": true
    }
  ],
  "id": "AC-003",
  "requirement": "FR-002",
  "severity": "major",
  "then": [
    {
      "operator": "eq",
      "path": "result.observations",
      "value": [
        {
          "exit_code": 0,
          "output": {
            "task": {
              "id": 1,
              "status": "completed",
              "title": "Buy milk"
            }
          }
        },
        {
          "exit_code": 0,
          "output": {
            "tasks": [
              {
                "id": 1,
                "status": "completed",
                "title": "Buy milk"
              },
              {
                "id": 2,
                "status": "open",
                "title": "Read book"
              }
            ]
          }
        }
      ]
    },
    {
      "operator": "eq",
      "path": "result.setup_observations",
      "value": [
        {
          "exit_code": 0,
          "output": {
            "task": {
              "id": 1,
              "status": "open",
              "title": "Buy milk"
            }
          }
        },
        {
          "exit_code": 0,
          "output": {
            "task": {
              "id": 2,
              "status": "open",
              "title": "Read book"
            }
          }
        }
      ]
    },
    {
      "operator": "eq",
      "path": "result.process_count",
      "value": 4
    }
  ],
  "when": {
    "action": "task_tracker.observe",
    "arguments": {
      "fixture": "empty",
      "setup": [
        [
          "create",
          "Buy milk"
        ],
        [
          "create",
          "Read book"
        ]
      ],
      "steps": [
        [
          "complete",
          "1"
        ],
        [
          "list"
        ]
      ]
    }
  }
}
```

### AC-004 — Major

Open, completed and all filters return exactly the correct partition, ordered by ID.

```json
{
  "criterion": "Open, completed and all filters return exactly the correct partition, ordered by ID.",
  "given": [
    {
      "operator": "eq",
      "path": "acceptance.ready",
      "value": true
    }
  ],
  "id": "AC-004",
  "requirement": "FR-003",
  "severity": "major",
  "then": [
    {
      "operator": "eq",
      "path": "result.observations",
      "value": [
        {
          "exit_code": 0,
          "output": {
            "tasks": [
              {
                "id": 2,
                "status": "open",
                "title": "Read book"
              }
            ]
          }
        },
        {
          "exit_code": 0,
          "output": {
            "tasks": [
              {
                "id": 1,
                "status": "completed",
                "title": "Buy milk"
              }
            ]
          }
        },
        {
          "exit_code": 0,
          "output": {
            "tasks": [
              {
                "id": 1,
                "status": "completed",
                "title": "Buy milk"
              },
              {
                "id": 2,
                "status": "open",
                "title": "Read book"
              }
            ]
          }
        }
      ]
    },
    {
      "operator": "eq",
      "path": "result.setup_observations",
      "value": [
        {
          "exit_code": 0,
          "output": {
            "task": {
              "id": 1,
              "status": "open",
              "title": "Buy milk"
            }
          }
        },
        {
          "exit_code": 0,
          "output": {
            "task": {
              "id": 2,
              "status": "open",
              "title": "Read book"
            }
          }
        },
        {
          "exit_code": 0,
          "output": {
            "task": {
              "id": 1,
              "status": "completed",
              "title": "Buy milk"
            }
          }
        }
      ]
    },
    {
      "operator": "eq",
      "path": "result.process_count",
      "value": 6
    }
  ],
  "when": {
    "action": "task_tracker.observe",
    "arguments": {
      "fixture": "empty",
      "setup": [
        [
          "create",
          "Buy milk"
        ],
        [
          "create",
          "Read book"
        ],
        [
          "complete",
          "1"
        ]
      ],
      "steps": [
        [
          "list",
          "--status",
          "open"
        ],
        [
          "list",
          "--status",
          "completed"
        ],
        [
          "list",
          "--status",
          "all"
        ]
      ]
    }
  }
}
```

### AC-005 — Critical

Across process restarts, completed task 1 and open task 2 persist; the next creation receives ID 3.

```json
{
  "criterion": "Across process restarts, completed task 1 and open task 2 persist; the next creation receives ID 3.",
  "given": [
    {
      "operator": "eq",
      "path": "acceptance.ready",
      "value": true
    }
  ],
  "id": "AC-005",
  "requirement": "FR-004",
  "severity": "critical",
  "then": [
    {
      "operator": "eq",
      "path": "result.observations",
      "value": [
        {
          "exit_code": 0,
          "output": {
            "task": {
              "id": 1,
              "status": "open",
              "title": "Buy milk"
            }
          }
        },
        {
          "exit_code": 0,
          "output": {
            "task": {
              "id": 2,
              "status": "open",
              "title": "Read book"
            }
          }
        },
        {
          "exit_code": 0,
          "output": {
            "task": {
              "id": 1,
              "status": "completed",
              "title": "Buy milk"
            }
          }
        },
        {
          "exit_code": 0,
          "output": {
            "tasks": [
              {
                "id": 1,
                "status": "completed",
                "title": "Buy milk"
              },
              {
                "id": 2,
                "status": "open",
                "title": "Read book"
              }
            ]
          }
        },
        {
          "exit_code": 0,
          "output": {
            "task": {
              "id": 3,
              "status": "open",
              "title": "Water plants"
            }
          }
        },
        {
          "exit_code": 0,
          "output": {
            "tasks": [
              {
                "id": 1,
                "status": "completed",
                "title": "Buy milk"
              }
            ]
          }
        }
      ]
    },
    {
      "operator": "eq",
      "path": "result.setup_observations",
      "value": []
    },
    {
      "operator": "eq",
      "path": "result.process_count",
      "value": 6
    }
  ],
  "when": {
    "action": "task_tracker.observe",
    "arguments": {
      "fixture": "empty",
      "steps": [
        [
          "create",
          "Buy milk"
        ],
        [
          "create",
          "Read book"
        ],
        [
          "complete",
          "1"
        ],
        [
          "list"
        ],
        [
          "create",
          "Water plants"
        ],
        [
          "list",
          "--status",
          "completed"
        ]
      ]
    }
  }
}
```

### AC-006 — Major

Repeated creation of the exact same title intentionally creates two tasks with distinct persistent IDs.

```json
{
  "criterion": "Repeated creation of the exact same title intentionally creates two tasks with distinct persistent IDs.",
  "given": [
    {
      "operator": "eq",
      "path": "acceptance.ready",
      "value": true
    }
  ],
  "id": "AC-006",
  "requirement": "FR-006",
  "severity": "major",
  "then": [
    {
      "operator": "eq",
      "path": "result.observations",
      "value": [
        {
          "exit_code": 0,
          "output": {
            "task": {
              "id": 1,
              "status": "open",
              "title": "Buy milk"
            }
          }
        },
        {
          "exit_code": 0,
          "output": {
            "task": {
              "id": 2,
              "status": "open",
              "title": "Buy milk"
            }
          }
        },
        {
          "exit_code": 0,
          "output": {
            "tasks": [
              {
                "id": 1,
                "status": "open",
                "title": "Buy milk"
              },
              {
                "id": 2,
                "status": "open",
                "title": "Buy milk"
              }
            ]
          }
        }
      ]
    },
    {
      "operator": "eq",
      "path": "result.setup_observations",
      "value": []
    },
    {
      "operator": "eq",
      "path": "result.process_count",
      "value": 3
    }
  ],
  "when": {
    "action": "task_tracker.observe",
    "arguments": {
      "fixture": "empty",
      "steps": [
        [
          "create",
          "Buy milk"
        ],
        [
          "create",
          "Buy milk"
        ],
        [
          "list"
        ]
      ]
    }
  }
}
```

### AC-007 — Major

Completing an already completed task again returns success with the same task; state and the other task remain unchanged.

```json
{
  "criterion": "Completing an already completed task again returns success with the same task; state and the other task remain unchanged.",
  "given": [
    {
      "operator": "eq",
      "path": "acceptance.ready",
      "value": true
    }
  ],
  "id": "AC-007",
  "requirement": "FR-006",
  "severity": "major",
  "then": [
    {
      "operator": "eq",
      "path": "result.observations",
      "value": [
        {
          "exit_code": 0,
          "output": {
            "task": {
              "id": 1,
              "status": "completed",
              "title": "Buy milk"
            }
          }
        },
        {
          "exit_code": 0,
          "output": {
            "task": {
              "id": 1,
              "status": "completed",
              "title": "Buy milk"
            }
          }
        },
        {
          "exit_code": 0,
          "output": {
            "tasks": [
              {
                "id": 1,
                "status": "completed",
                "title": "Buy milk"
              },
              {
                "id": 2,
                "status": "open",
                "title": "Read book"
              }
            ]
          }
        }
      ]
    },
    {
      "operator": "eq",
      "path": "result.setup_observations",
      "value": [
        {
          "exit_code": 0,
          "output": {
            "task": {
              "id": 1,
              "status": "open",
              "title": "Buy milk"
            }
          }
        },
        {
          "exit_code": 0,
          "output": {
            "task": {
              "id": 2,
              "status": "open",
              "title": "Read book"
            }
          }
        },
        {
          "exit_code": 0,
          "output": {
            "task": {
              "id": 1,
              "status": "completed",
              "title": "Buy milk"
            }
          }
        }
      ]
    },
    {
      "operator": "eq",
      "path": "result.process_count",
      "value": 6
    }
  ],
  "when": {
    "action": "task_tracker.observe",
    "arguments": {
      "fixture": "empty",
      "setup": [
        [
          "create",
          "Buy milk"
        ],
        [
          "create",
          "Read book"
        ],
        [
          "complete",
          "1"
        ]
      ],
      "steps": [
        [
          "complete",
          "1"
        ],
        [
          "complete",
          "1"
        ],
        [
          "list"
        ]
      ]
    }
  }
}
```

### AC-008 — Major

Empty and whitespace-only titles return INVALID_TITLE with exit 2 and create no task.

```json
{
  "criterion": "Empty and whitespace-only titles return INVALID_TITLE with exit 2 and create no task.",
  "given": [
    {
      "operator": "eq",
      "path": "acceptance.ready",
      "value": true
    }
  ],
  "id": "AC-008",
  "requirement": "FR-005",
  "severity": "major",
  "then": [
    {
      "operator": "eq",
      "path": "result.observations",
      "value": [
        {
          "exit_code": 2,
          "output": {
            "error": "INVALID_TITLE"
          }
        },
        {
          "exit_code": 2,
          "output": {
            "error": "INVALID_TITLE"
          }
        },
        {
          "exit_code": 0,
          "output": {
            "tasks": []
          }
        }
      ]
    },
    {
      "operator": "eq",
      "path": "result.setup_observations",
      "value": []
    },
    {
      "operator": "eq",
      "path": "result.process_count",
      "value": 3
    }
  ],
  "when": {
    "action": "task_tracker.observe",
    "arguments": {
      "fixture": "empty",
      "steps": [
        [
          "create",
          ""
        ],
        [
          "create",
          "   "
        ],
        [
          "list"
        ]
      ]
    }
  }
}
```

### AC-009 — Major

Zero, negative and noninteger IDs return INVALID_ID; unknown positive ID 999 returns NOT_FOUND; existing state is unchanged.

```json
{
  "criterion": "Zero, negative and noninteger IDs return INVALID_ID; unknown positive ID 999 returns NOT_FOUND; existing state is unchanged.",
  "given": [
    {
      "operator": "eq",
      "path": "acceptance.ready",
      "value": true
    }
  ],
  "id": "AC-009",
  "requirement": "FR-005",
  "severity": "major",
  "then": [
    {
      "operator": "eq",
      "path": "result.observations",
      "value": [
        {
          "exit_code": 2,
          "output": {
            "error": "INVALID_ID"
          }
        },
        {
          "exit_code": 2,
          "output": {
            "error": "INVALID_ID"
          }
        },
        {
          "exit_code": 2,
          "output": {
            "error": "INVALID_ID"
          }
        },
        {
          "exit_code": 2,
          "output": {
            "error": "NOT_FOUND"
          }
        },
        {
          "exit_code": 0,
          "output": {
            "tasks": [
              {
                "id": 1,
                "status": "open",
                "title": "Buy milk"
              }
            ]
          }
        }
      ]
    },
    {
      "operator": "eq",
      "path": "result.setup_observations",
      "value": [
        {
          "exit_code": 0,
          "output": {
            "task": {
              "id": 1,
              "status": "open",
              "title": "Buy milk"
            }
          }
        }
      ]
    },
    {
      "operator": "eq",
      "path": "result.process_count",
      "value": 6
    }
  ],
  "when": {
    "action": "task_tracker.observe",
    "arguments": {
      "fixture": "empty",
      "setup": [
        [
          "create",
          "Buy milk"
        ]
      ],
      "steps": [
        [
          "complete",
          "0"
        ],
        [
          "complete",
          "-1"
        ],
        [
          "complete",
          "abc"
        ],
        [
          "complete",
          "999"
        ],
        [
          "list"
        ]
      ]
    }
  }
}
```

### AC-010 — Major

Unsupported status done returns INVALID_STATUS with exit 2; existing state is unchanged.

```json
{
  "criterion": "Unsupported status done returns INVALID_STATUS with exit 2; existing state is unchanged.",
  "given": [
    {
      "operator": "eq",
      "path": "acceptance.ready",
      "value": true
    }
  ],
  "id": "AC-010",
  "requirement": "FR-005",
  "severity": "major",
  "then": [
    {
      "operator": "eq",
      "path": "result.observations",
      "value": [
        {
          "exit_code": 2,
          "output": {
            "error": "INVALID_STATUS"
          }
        },
        {
          "exit_code": 0,
          "output": {
            "tasks": [
              {
                "id": 1,
                "status": "open",
                "title": "Buy milk"
              }
            ]
          }
        }
      ]
    },
    {
      "operator": "eq",
      "path": "result.setup_observations",
      "value": [
        {
          "exit_code": 0,
          "output": {
            "task": {
              "id": 1,
              "status": "open",
              "title": "Buy milk"
            }
          }
        }
      ]
    },
    {
      "operator": "eq",
      "path": "result.process_count",
      "value": 3
    }
  ],
  "when": {
    "action": "task_tracker.observe",
    "arguments": {
      "fixture": "empty",
      "setup": [
        [
          "create",
          "Buy milk"
        ]
      ],
      "steps": [
        [
          "list",
          "--status",
          "done"
        ],
        [
          "list"
        ]
      ]
    }
  }
}
```

### AC-011 — Critical

Malformed existing storage returns STORE_INVALID with exit 1, preserves the original bytes and does not silently reset data.

```json
{
  "criterion": "Malformed existing storage returns STORE_INVALID with exit 1, preserves the original bytes and does not silently reset data.",
  "given": [
    {
      "operator": "eq",
      "path": "acceptance.ready",
      "value": true
    }
  ],
  "id": "AC-011",
  "requirement": "FR-004",
  "severity": "critical",
  "then": [
    {
      "operator": "eq",
      "path": "result.observations",
      "value": [
        {
          "exit_code": 1,
          "output": {
            "error": "STORE_INVALID"
          }
        }
      ]
    },
    {
      "operator": "eq",
      "path": "result.setup_observations",
      "value": []
    },
    {
      "operator": "eq",
      "path": "result.process_count",
      "value": 1
    },
    {
      "operator": "eq",
      "path": "result.store_unchanged",
      "value": true
    }
  ],
  "when": {
    "action": "task_tracker.observe",
    "arguments": {
      "fixture": "corrupt",
      "steps": [
        [
          "list"
        ]
      ]
    }
  }
}
```

### AC-012 — Critical

A creation that cannot persist because its store parent is a regular file returns STORE_IO with exit 1 and never acknowledges success.

```json
{
  "criterion": "A creation that cannot persist because its store parent is a regular file returns STORE_IO with exit 1 and never acknowledges success.",
  "given": [
    {
      "operator": "eq",
      "path": "acceptance.ready",
      "value": true
    }
  ],
  "id": "AC-012",
  "requirement": "FR-004",
  "severity": "critical",
  "then": [
    {
      "operator": "eq",
      "path": "result.observations",
      "value": [
        {
          "exit_code": 1,
          "output": {
            "error": "STORE_IO"
          }
        }
      ]
    },
    {
      "operator": "eq",
      "path": "result.setup_observations",
      "value": []
    },
    {
      "operator": "eq",
      "path": "result.process_count",
      "value": 1
    }
  ],
  "when": {
    "action": "task_tracker.observe",
    "arguments": {
      "fixture": "unwritable",
      "steps": [
        [
          "create",
          "Buy milk"
        ]
      ]
    }
  }
}
```

### AC-013 — Critical

After ten strictly sequential creates, each process exits before the next starts. A new list process must find every acknowledged record: zero records missing. The observer counts distinct valid acknowledgements; at least ten are required. Concurrent creation is out of scope; do not test parallel writers.

Workload: ten strictly sequential creates, each process exiting before the next starts;
fresh titles in one fresh store, then a new list process. Units: records missing.
Concurrent creation is out of scope; do not test parallel writers.

```json
{
  "criterion": "After ten strictly sequential creates, each process exits before the next starts. A new list process must find every acknowledged record: zero records missing. The observer counts distinct valid acknowledgements; at least ten are required. Concurrent creation is out of scope; do not test parallel writers.",
  "id": "AC-013",
  "measure": "task_tracker.missing_acknowledged_records",
  "operator": "eq",
  "requirement": "FR-004",
  "sample": {
    "minimum": 10
  },
  "severity": "critical",
  "value": 0
}
```

### AC-014 — Critical

In a fresh store, reject a blank title, then create a valid task. The valid task receives ID 1 and the store contains exactly that one task. A rejected create must not advance the next-ID counter.

```json
{
  "criterion": "In a fresh store, reject a blank title, then create a valid task. The valid task receives ID 1 and the store contains exactly that one task. A rejected create must not advance the next-ID counter.",
  "given": [
    {
      "operator": "eq",
      "path": "acceptance.ready",
      "value": true
    }
  ],
  "id": "AC-014",
  "requirement": "FR-001",
  "severity": "critical",
  "then": [
    {
      "operator": "eq",
      "path": "result.observations",
      "value": [
        {
          "exit_code": 2,
          "output": {
            "error": "INVALID_TITLE"
          }
        },
        {
          "exit_code": 0,
          "output": {
            "task": {
              "id": 1,
              "status": "open",
              "title": "Buy milk"
            }
          }
        },
        {
          "exit_code": 0,
          "output": {
            "tasks": [
              {
                "id": 1,
                "status": "open",
                "title": "Buy milk"
              }
            ]
          }
        }
      ]
    },
    {
      "operator": "eq",
      "path": "result.setup_observations",
      "value": []
    },
    {
      "operator": "eq",
      "path": "result.process_count",
      "value": 3
    }
  ],
  "when": {
    "action": "task_tracker.observe",
    "arguments": {
      "fixture": "empty",
      "steps": [
        [
          "create",
          ""
        ],
        [
          "create",
          "Buy milk"
        ],
        [
          "list"
        ]
      ]
    }
  }
}
```

## Binary release gates

- description: Every approved AC-001 through AC-014 passes unchanged; severity does not permit skipping a criterion.; id: GATE-001
- description: The meaningful baseline fails by assertion; isolated persistence and filtering mutations fail unchanged checks for the intended behavior, not a missing prerequisite or arbitrary crash.; id: GATE-002
- description: Every approval-bound digest matches immediately before and immediately after each authoritative check. A mismatch fails the run, regardless of its behavioral verdict.; id: GATE-003
- description: Actual in-session model request/response evidence, exact commands, generated artifact and criterion-linked observations are retained; no undisclosed manual repair.; id: GATE-004
- description: Report root privileges, forgeable receipts, active-session reproduction and the environment-blocked real-sandbox leg. An allowed weaker-isolation run cannot be represented as full isolation or general readiness.; id: GATE-005

## Scored eval rubric

- criterion: Report functional evidence coverage as approved criteria with independently observed passing behavior divided by all fourteen criteria; this descriptive score cannot override any binary gate.; id: RUB-001; scale: 0 through 14 passed criteria

## Non functional requirements

- category: durability; id: NFR-001; requirement: A successful task acknowledgement remains observable after that process exits and another process opens the same store.
- category: measurement; id: NFR-002; requirement: AC-013 runs ten strictly sequential creates, each process exiting before the next starts, in a fresh temporary store with fresh titles; then a new list process observes the stored records. Units are records missing after restart, threshold exactly zero, sample.minimum ten distinct valid acknowledgements. Concurrent creation is out of scope; do not test parallel writers. This is deterministic, not statistical AI quality or a latency claim.
- category: execution; id: NFR-003; requirement: Standard-library CLI with no paid dependency. Execution limits, file-handoff provider and admitted weaker-isolation limitations are pinned in execution-profile.json.

## Approved product decisions

- decision: Owner approved a local task tracker with create, complete, status filtering and persistence across restart; CLI is sufficient.; id: APD-001
- decision: Owner approved cloud-only in-session file handoff, the supplied BAR Gate and no paid model API.; id: APD-002
- decision: Owner replaced prevention with before/after artifact-digest checks, retained root access and receipt forgery as limitations, and deferred signing repair.; id: APD-003
- decision: Owner authorized testing only the network-unsharing removal, and an explicitly reported weaker-isolation candidate run if the environment still blocks the real sandbox.; id: APD-004
- decision: Owner approved exactly the proposed increasing positive integer identifiers, distinct tasks on duplicate creation and idempotent repeated completion.; id: APD-005
- decision: Owner requires strictly sequential AC-013 with each create process exiting before the next starts; concurrent creation is out of scope and parallel writers must not be tested.; id: APD-006
- decision: Owner requires critical AC-014: reject a blank title, then create a valid task with ID 1 and exactly one stored task. A rejected create must not advance the next-ID counter.; id: APD-007
- decision: Owner closed the sandbox decision: no more Bubblewrap attempts; use the documented fallback and state every absent isolation. Approval-forgery repair remains deferred.; id: APD-008

## Required approvals

- for: Owner requested one-line confirmation of the amended grid before freezing this exact DRAFT contract, acceptance grid, evaluator and digest manifest, then continuing to Phases 3 and 4. The previously proposed identifier, duplicate and repeated-completion rules are already approved.; role: product-owner
- for: Renew approval for changes affecting artifact, evaluator or execution-profile meaning.; role: product-owner

## Measurement

Proposed outcome: share of approved task-management journeys completed with correct durable state and no manual repair. This one-feature experiment does not estimate representative platform delivery rate.

- First-pass contract compatibility; first-attempt criterion pass count; model build attempts.
- No approved requirement or expected outcome changed to obtain a pass.
- All missing records count in AC-013 and failed acknowledgement workload cannot pass its minimum sample.
- Track false passes against known-bad candidates, manual interventions, actual runtime and available usage without inventing token or cost figures.
- Root access and forgeable receipts remain permanent limitations; recorded digests are tamper evidence, not prevention.

The AC-013 count is deterministic. It establishes neither statistical AI quality
nor production latency. Report all 14 criterion outcomes; no ratio overrides a failure.

## Named limitations and execution

**Creation is not idempotent. Duplicate-on-retry is approved behavior, not a defect.**
No retry-safety claim for create; completion idempotency is covered by AC-007.
Concurrent creation is out of scope. No parallel writers are tested.

- Root can modify evaluator/checker/evidence or change and restore bytes between digest observations; this run does not establish adversarial tamper prevention.
- Existing approval receipts can be forged from public hashes; external signing authority is deferred by owner direction.
- The real sandbox still cannot establish a UID map in this environment; any candidate run here uses the expressly admitted weaker isolation and must state dropped protections.
- Named limitation — Creation is not idempotent. Duplicate-on-retry is approved behavior, not a defect; this experiment must not claim retry-safety for create. Completion idempotency is covered by AC-007.

**Sandbox: closed by owner direction. Do not attempt Bubblewrap again.**
The existing --unshare-all --share-net retry and explicit namespace probe failed
with `bwrap: setting up uid map: Operation not permitted`. Every other original
sandbox argument was retained. Exact commands and evidence: https://github.com/Abhillashjadhav/production-engineering-os/blob/audit/task-tracker-seam/docs/evidence/task-tracker-audit-20260918/owner-amendment.md
The real-sandbox leg is blocked by environment. The authorized existing-container
fallback lacks these additional protections:

- candidate user namespace
- candidate PID namespace
- candidate mount namespace and read-only runtime/candidate mounts
- candidate IPC namespace
- candidate UTS namespace
- candidate cgroup namespace
- candidate network namespace
- candidate private tmpfs and /proc

Retained controls:

- existing process timeouts and budgets
- prlimit resource caps where executable
- candidate path and output validation
- all approved acceptance assertions
- before/after tamper checks

Resource caps:

```json
{
  "action_cpu_seconds": 11,
  "action_timeout_seconds": 10,
  "address_space_bytes": 1073741824,
  "file_size_bytes": 67108864,
  "open_files": 256,
  "per_cli_process_timeout_seconds": 2,
  "processes": 128
}
```

Configured prlimit values observed in a harmless process; enforcement was not stress-tested, and root privilege remains a limitation.

## Tamper evidence and approval

- At owner approval, verify the reviewed bundle digest; derive the approved contract and receipt using the existing publisher; record all concrete artifact digests and exact paths.
- Immediately before each authoritative criterion/check process, recompute every approval-bound digest and compare against the approval-time snapshot; any mismatch fails the run before evaluation.
- Immediately after each check, including nonzero exit, exception or timeout, repeat the comparisons and retain before/after observations with the criterion ID; mismatch overrides a passing result.
- Any artifact or profile change affecting meaning requires renewed approval; do not update the trusted expected digest to make a run pass.

Permanent limitations and audit corrections:

- Builder and orchestrator run as root. Prevention of evaluator/approval modification is not established.
- Before/after hashes can expose observed changes; a root process can rewrite the checker or evidence, or make and restore a transient change between observations. This is not adversarial tamper prevention.
- Existing approval receipts can be forged by recomputing public hashes. No signing-authority fix is included; owner approval is captured in the conversation.
- Historical live-provider evidence exists in PEOS and was not independently verified by this run.
- New business actions already work through the Template API without engine-source edits; the remaining access work is a declarative file and CLI loader path.
- One feature, deterministic measurement and weaker-isolation run cannot establish broad reliability or production readiness.
- Creation is not idempotent. Duplicate-on-retry is approved behavior, not a defect. No retry-safety claim for create; AC-007 covers completion idempotency.
- Concurrent creation is out of scope. AC-013 is strictly sequential: each create process exits before the next starts. Do not test parallel writers.

The provider requires an active agent session; no headless model reproduction is claimed.
New business actions do not require an engine-source change, only a CLI path.
Prior live-provider evidence already exists in PEOS, unverified by this run.
Root privileges remain a limitation; hashes are tamper evidence, not prevention.
Approval-forgery repair is deferred. One feature establishes feasibility only.

## Freeze boundary

The owner confirmed the amended grid and authorized full-document regeneration
before the freeze. Contract, grid, evaluator and prepared manifest must agree
before approval-time digests are recorded. No criterion or evaluator meaning changes.
If later CLI/enforcement work changes a bound source file, update the review manifest and obtain renewed approval before product generation. Do not treat this proposal as approval of source bytes that do not yet exist.
