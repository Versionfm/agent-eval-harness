"""Selected-point state versus final state for one recorded attempt (ticket #13 experiment).

Usage: PYTHONPATH=live-tracker/src python live-tracker/experiments/selected_point.py <attempt-directory>

For each model and tool outcome, prints the state the workbench shows when that event is
selected: the newest state event at or before the selection. Later events are never used.
The last row shows the final state, which is only reached after attempt_finished.
"""

import sys
from pathlib import Path

from live_tracker.reader import read_attempt_history


def selected_state(events, sequence):
    found = None
    for event in events:
        if event["sequence"] > sequence:
            break
        if event["type"] == "state":
            found = event
    return found


def main(argv):
    events = read_attempt_history(Path(argv[1])).events
    print("| selected | event | model calls | context bytes | tool result messages | state from |")
    print("|---:|---|---:|---:|---:|---|")
    rows = []
    for event in events:
        if event["type"] not in {"model.outcome", "tool.outcome"}:
            continue
        state = selected_state(events, event["sequence"])
        data = state["data"] if state else {}
        rows.append((event["sequence"], f"{event['type']} {event.get('operation_id', '')}", data, state))
    final = selected_state(events, events[-1]["sequence"])
    for sequence, label, data, state in rows:
        source = f"#{state['sequence']}" if state else "none"
        print(f"| #{sequence} | {label} | {data.get('model_calls')} / {data.get('max_model_calls')} | "
              f"{data.get('context_bytes')} | {data.get('tool_result_messages')} | {source} |")
    final_data = final["data"]
    print(f"| #{events[-1]['sequence']} | attempt_finished (final state, #{final['sequence']}) | "
          f"{final_data['model_calls']} / {final_data['max_model_calls']} | {final_data['context_bytes']} | "
          f"{final_data['tool_result_messages']} | #{final['sequence']} |")

    # The first tool outcome must not already know the context that later turns add.
    first_tool = next(data for _, label, data, _ in rows if label.startswith("tool.outcome"))
    assert first_tool["context_bytes"] < final_data["context_bytes"], "selected state leaked later context"
    assert first_tool["model_calls"] < final_data["model_calls"], "selected state leaked later calls"


if __name__ == "__main__":
    main(sys.argv)
