"""Optional Feynman state; legacy reads never infer a completed human exercise."""
from __future__ import annotations

import copy
from datetime import date

MODES = {'standard', 'blank_sheet'}
STATUSES = {'not_requested', 'active', 'paused', 'complete'}
FIELDS = {'status', 'mode', 'requested_at', 'paused_at', 'reason', 'history'}


def iso_date(value):
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def new_learning(mode=None, requested_at=None):
    """A CLI opt-in records a request, never learning or research completion."""
    if mode == 'off':
        mode = None
    if mode is not None and (not isinstance(mode, str) or mode not in MODES):
        raise ValueError('Feynman mode must be off, standard, or blank_sheet')
    if mode is not None and not iso_date(requested_at):
        raise ValueError('Explicit Feynman request requires its actual date')
    return {'schema_version': 1, 'feynman': {
        'status': 'active' if mode else 'not_requested', 'mode': mode,
        'requested_at': requested_at if mode else None, 'paused_at': None,
        'reason': 'Explicitly requested exercise.' if mode else 'Optional exercise not requested.',
        'history': [],
    }}


def validate_learning(metadata):
    """Validate the additive contract without requiring migration of old items."""
    if 'learning' not in metadata:
        return []
    data = metadata['learning']
    if not isinstance(data, dict):
        return ['learning must be an object']
    errors = []
    if set(data) != {'schema_version', 'feynman'}:
        errors.append('learning requires only schema_version and feynman')
    if type(data.get('schema_version')) is not int or data.get('schema_version') != 1:
        errors.append('learning.schema_version must be integer 1')
    exercise = data.get('feynman')
    if not isinstance(exercise, dict):
        return errors + ['learning.feynman must be an object']
    if set(exercise) != FIELDS:
        errors.append('learning.feynman fields do not match version 1')
    status, mode = exercise.get('status'), exercise.get('mode')
    if not isinstance(status, str) or status not in STATUSES:
        errors.append('learning.feynman.status is invalid')
    if mode is not None and (not isinstance(mode, str) or mode not in MODES):
        errors.append('learning.feynman.mode is invalid')
    if status == 'not_requested' and (mode is not None or exercise.get('requested_at') is not None or exercise.get('paused_at') is not None):
        errors.append('An unrequested exercise has no mode or event dates')
    if status in ('active', 'paused', 'complete') and mode not in ('standard', 'blank_sheet'):
        errors.append('A requested exercise requires its mode')
    for field in ('requested_at', 'paused_at'):
        value = exercise.get(field)
        if value is not None and not iso_date(value):
            errors.append('learning.feynman.' + field + ' must be an ISO date or null')
    if status in ('active', 'complete') and exercise.get('requested_at') is None:
        errors.append('An active or completed exercise requires a request date')
    if status in ('active', 'complete') and exercise.get('paused_at') is not None:
        errors.append('An active or completed exercise has no current pause date')
    if iso_date(exercise.get('requested_at')) and iso_date(exercise.get('paused_at')) and exercise['paused_at'] < exercise['requested_at']:
        errors.append('Pause date precedes the request')
    if not isinstance(exercise.get('reason'), str) or not exercise['reason'].strip():
        errors.append('learning.feynman.reason is required')
    history = exercise.get('history')
    if not isinstance(history, list) or any(not isinstance(entry, dict) for entry in history):
        errors.append('learning.feynman.history must contain objects')
    else:
        previous_at = None
        for entry in history:
            at = entry.get('at')
            if (not iso_date(at) or entry.get('action') not in ('pause', 'resume')
                    or not isinstance(entry.get('reason'), str) or not entry['reason'].strip()
                    or not isinstance(entry.get('before'), dict)):
                errors.append('Exercise history needs an ISO date, action, reason, and before snapshot')
            elif previous_at and at < previous_at:
                errors.append('Exercise history dates must be chronological')
            if iso_date(at):
                previous_at = at
    route = metadata.get('route')
    if not isinstance(route, dict):
        return errors + ['learning requires a route object']
    selected = route.get('selected')
    if not isinstance(selected, list) or any(not isinstance(stage, str) for stage in selected):
        return errors + ['learning requires route.selected to be a list of stages']
    if status == 'active' and 'understand' not in selected:
        errors.append('An active Feynman exercise requires an Understand route')
    # Retained legacy mode is a compatibility assertion, never another authority.
    if 'feynman_mode' in route:
        legacy = route['feynman_mode']
        equivalent = (legacy == mode and mode is not None) or (mode is None and legacy in ('off', 'skipped', 'legacy_written_only', None))
        if not equivalent:
            errors.append('Legacy route.feynman_mode conflicts with learning.feynman.mode')
    return errors


def read_learning(metadata):
    """Read canonical state or provide a conservative, non-writing legacy view."""
    errors = validate_learning(metadata)
    if errors:
        raise ValueError('; '.join(errors))
    if 'learning' in metadata:
        return copy.deepcopy(metadata['learning'])
    result = new_learning()
    route = metadata.get('route') or {}
    legacy = route.get('feynman_mode')
    if legacy in ('standard', 'blank_sheet') and 'understand' in (route.get('selected') or []):
        result['feynman'].update(status='paused', mode=legacy,
            reason='Legacy exercise; status and dates require review before explicit resumption.')
    else:
        result['feynman']['reason'] = 'Legacy record; no active exercise inferred. Preserve prior written work.'
    return result


def transition_learning(metadata, action, changed_at, reason):
    """Return a changed copy for a later writer; never change paper lifecycle."""
    if action not in ('pause', 'resume') or not iso_date(changed_at) or not isinstance(reason, str) or not reason.strip():
        raise ValueError('Use pause or resume with an ISO date and reason')
    updated = copy.deepcopy(metadata)
    learning = read_learning(metadata)
    item = learning['feynman']
    dates = [item.get('requested_at'), item.get('paused_at')]
    dates.extend(entry['at'] for entry in item['history'])
    if any(value and changed_at < value for value in dates):
        raise ValueError('An exercise transition cannot precede its recorded events')
    expected = 'active' if action == 'pause' else 'paused'
    if item['status'] != expected:
        raise ValueError(f'{action} requires {expected} exercise status')
    item['history'].append({'at': changed_at, 'action': action, 'reason': reason,
                            'before': {k: copy.deepcopy(v) for k, v in item.items() if k != 'history'}})
    item['status'] = 'paused' if action == 'pause' else 'active'
    item['paused_at'] = changed_at if action == 'pause' else None
    if action == 'resume' and item['requested_at'] is None:
        item['requested_at'] = changed_at
    item['reason'] = reason
    updated['learning'] = learning
    errors = validate_learning(updated)
    if errors:
        raise ValueError('; '.join(errors))
    return updated
