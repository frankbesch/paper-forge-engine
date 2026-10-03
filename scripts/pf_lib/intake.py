"""Version-two intake drafts. Deterministic structure; the assistant supplies judgments."""
from __future__ import annotations
import re
from pathlib import PurePosixPath

TEXT_FIELDS = ('idea', 'support', 'unknowns', 'potential_use', 'effort', 'risk', 'next_action')
APPLICATION_FIELDS = {'purpose', 'destination', 'project_path', 'artifact_type', 'item_ids', 'evidence_limits', 'success_check'}

def pending_assessment(metadata, today, endeavors=()):
    from .assessment import empty_assessment
    result = empty_assessment(metadata['item_id'], 'capture (no assessor)', today, endeavors)
    identity = metadata.get('identity') or {}
    sources = metadata.get('sources') or []
    result.update(assessment_version=2, status='pending', recommendation=None,
        intake={**{key: None for key in TEXT_FIELDS}, 'confidence': None,
            'attribution': 'partial' if identity.get('authors') or any(s.get('canonical_url') for s in sources) else 'unknown',
            'citations': [s['canonical_url'] for s in sources if s.get('canonical_url')],
            'evidence_locations': [], 'conflicts': [], 'failure': None})
    result['intake']['next_action'] = f"Read preserved sources; draft assessment with pf.py intake {metadata['item_id']} --from <draft.json>."
    return result

def relative_path(value):
    return isinstance(value, str) and bool(value.strip()) and not value.startswith(('~', '/', '\\')) and '\\' not in value and ':' not in value and '..' not in PurePosixPath(value).parts

def validate_application(app, item_id, destinations=None):
    """destinations: configured export targets plus paper-forge; any lowercase key when None."""
    if not isinstance(app, dict) or set(app) != APPLICATION_FIELDS:
        return ['application fields must match the version-two contract']
    errors = []
    for key in APPLICATION_FIELDS - {'item_ids'}:
        if not isinstance(app[key], str) or not app[key].strip():
            errors.append(f'application.{key} requires text')
    if destinations is not None and app['destination'] not in destinations:
        errors.append(f"application destination must be one of {sorted(destinations)}")
    elif destinations is None and not re.fullmatch(r'[a-z0-9][a-z0-9-]*', str(app['destination'])):
        errors.append('application destination must be a lowercase target key')
    if not relative_path(app['project_path']):
        errors.append('application project_path must be a safe relative path')
    ids = app['item_ids']
    if not isinstance(ids, list) or not ids or any(not isinstance(i, str) or not re.fullmatch(r'PF-\d{4,}', i) for i in ids):
        errors.append('application item_ids must contain Paper Forge IDs')
    elif ids[0] != item_id or len(ids) != len(set(ids)):
        errors.append('application must start with its owning item and contain unique source IDs')
    return errors

def validate_extension(doc, metadata):
    version, status = doc.get('assessment_version'), doc.get('status')
    if version == 1:
        return ['new assessment states and extensions require assessment_version 2'] if status in ('pending','draft','failed') or 'intake' in doc or 'recommendation' in doc else []
    if version != 2:
        return []  # Base validator reports the version.
    errors = []
    intake = doc.get('intake')
    fields = set(TEXT_FIELDS) | {'confidence', 'attribution', 'citations', 'evidence_locations', 'conflicts', 'failure'}
    if not isinstance(intake, dict) or set(intake) != fields:
        errors.append('intake fields must match version 2')
    else:
        for key in TEXT_FIELDS:
            value = intake[key]
            if value is not None and (not isinstance(value, str) or not value.strip()):
                errors.append(f'intake.{key} must be text or null')
            if status == 'draft' and not value:
                errors.append(f'draft intake requires {key}; state uncertainty explicitly')
        if not intake.get('next_action'):
            errors.append('intake requires a concrete next_action')
        if intake['confidence'] not in (None, 'low', 'medium', 'high'):
            errors.append('intake confidence is invalid')
        if status == 'draft' and intake['confidence'] is None:
            errors.append('draft requires confidence')
        if intake['attribution'] not in ('unknown', 'partial', 'verified'):
            errors.append('intake attribution is invalid')
        for key in ('citations', 'evidence_locations', 'conflicts'):
            if not isinstance(intake[key], list) or any(not isinstance(v, str) or not v.strip() for v in intake[key]):
                errors.append(f'intake.{key} must be a list of text')
        if intake['attribution'] == 'verified' and not intake['evidence_locations']:
            errors.append('verified external attribution needs verification evidence')
        if intake['failure'] is not None and (not isinstance(intake['failure'], str) or not intake['failure'].strip()):
            errors.append('intake.failure must be text or null')
        if status == 'failed' and not intake['failure']:
            errors.append('failed intake requires a failure receipt')
        if status != 'failed' and intake['failure'] is not None:
            errors.append('failure belongs only to failed status; preserve prior failures in history')
    if status in ('pending', 'draft', 'failed'):
        if doc.get('disposition') != {'value': None, 'rationale': None} or doc.get('application_state') != 'unassessed':
            errors.append('pending, draft, and failed assessments cannot set effective disposition or application state')
    recommendation = doc.get('recommendation')
    if 'recommendation' not in doc:
        errors.append('version 2 requires recommendation (null when pending)')
    if status == 'draft' and recommendation is None:
        errors.append('draft needs a recommendation')
    if recommendation is not None:
        from .assessment import DISPOSITIONS
        if not isinstance(recommendation, dict) or set(recommendation) != {'disposition', 'rationale', 'applications'}:
            errors.append('recommendation needs disposition, rationale, applications')
        else:
            if not isinstance(recommendation['disposition'], str) or recommendation['disposition'] not in DISPOSITIONS:
                errors.append('recommendation disposition is invalid')
            if not isinstance(recommendation['rationale'], str) or not recommendation['rationale'].strip():
                errors.append('recommendation rationale is required')
            if not isinstance(recommendation['applications'], list):
                errors.append('recommendation applications must be a list')
            else:
                for app in recommendation['applications']:
                    errors.extend(validate_application(app, metadata.get('item_id')))
    return errors
