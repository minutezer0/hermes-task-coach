"""Explicit authorization helpers for historical, fictional history fixtures only."""


def enable_history(runtime):
    """Opt this fixture's exact configured route in without rotating a live grant."""
    if not runtime.history_preference()['enabled']:
        runtime.history_preference(enabled=True, route=runtime.status()['route'], confirm=True)


def history_request(runtime, operation, token=None, fence=None, *, message_id=None,
                    reply_to_message_id=None, selection_message_id=None,
                    dismissal_message_id=None, **unused):
    """Build a real per-operation plan; never bypass or modify the ingress gate."""
    from task_coach.coaching import instant
    if operation == 'confirm':
        row = runtime.row(token, fence)
        target = row.get('candidate_id') or row.get('receipt', {}).get('message_id') or message_id
    elif operation == 'observe':
        target = runtime.row(token, fence)['previous']['receipt']['message_id']
    elif operation == 'engagement':
        rows = [row for row in runtime.status()['outbox'].values() if row['state'] == 'confirmed']
        selected = [row for row in rows if row['receipt']['message_id'] == reply_to_message_id] or rows
        target = max(selected, key=lambda row: (instant(row['receipt']['delivered_at']), int(row['receipt']['message_id'])))['receipt']['message_id']
    else:
        target = selection_message_id if operation == 'resolve_clarification' else dismissal_message_id
    return runtime.history_plan(purpose='delivery-verification' if operation == 'confirm' else 'reply-recovery',
                                target=target, confirm=True)


def history_cli(runtime, *args):
    """Append an actual bounded plan file to an explicit historical CLI request."""
    import json
    operation = args[0].replace('-', '_')
    values = {}
    for flag, name in (('--event-token', 'token'), ('--fence', 'fence'),
                       ('--message-id', 'message_id'), ('--reply-to-message-id', 'reply_to_message_id'),
                       ('--selection-message-id', 'selection_message_id'),
                       ('--dismissal-message-id', 'dismissal_message_id')):
        if flag in args:
            values[name] = args[args.index(flag) + 1]
    request = history_request(runtime, operation, **values)
    path = runtime.directory.parent / ('fictional-history-plan-' + operation + '-' + request['target'] + '.json')
    path.write_text(json.dumps(request))
    return (*args, '--history-plan-file', str(path))


def fictional_clock_command(command, now):
    """Run the real isolated launcher/parser at the fixture clock after restart."""
    from pathlib import Path
    launcher = command[3]
    source = ('import sys,runpy\nfrom datetime import datetime\n'
              'sys.path.insert(0, ' + repr(str(Path(launcher).parent)) + ')\n'
              'import task_coach.driver as driver\n'
              'class Clock(datetime):\n'
              ' @classmethod\n'
              ' def now(cls,tz=None): return datetime.fromisoformat(' + repr(now) + ').astimezone(tz)\n'
              'driver.datetime=Clock\nsys.argv=' + repr(command[3:]) + '\n'
              'runpy.run_path(' + repr(launcher) + ',run_name="__main__")\n')
    return [*command[:3], '-c', source]
