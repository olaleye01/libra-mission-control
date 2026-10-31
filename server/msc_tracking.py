"""Versioned interpretation of visible MSC tracking text, never of LLM output."""
import datetime as dt
import hashlib
import re
from zoneinfo import ZoneInfo

from msc_browser import CollectorError, URL

PARSER = 'msc-visible-text-v1'
CONTAINER = re.compile(r'[A-Z]{4}\d{7}')
DAY = re.compile(r'\d{2}/\d{2}/\d{4}')
NIGERIAN_PORTS = ('Onne, NG', 'Apapa, NG', 'Tincan/Lagos, NG', 'Lagos, NG', 'Lekki, NG',
                  'Port Harcourt, NG', 'Warri, NG', 'Calabar, NG')


def location(value):
    return re.sub(r'[^a-z0-9]', '', value.casefold())


def calendar(value):
    try:
        return dt.datetime.strptime(value, '%d/%m/%Y').date().isoformat()
    except ValueError:
        raise CollectorError('MSC returned an invalid event date; manual review is needed.')


def discover_destination(text):
    """Trust the explicit Port of Discharge header, never a transit event's location."""
    if not isinstance(text, str) or len(text) > 2*1024*1024:
        raise CollectorError('MSC returned an oversized or unreadable page.', code='invalid_page')
    lines = [re.sub(r'\s+', ' ', s).strip() for s in text.splitlines() if s.strip()]
    try:
        port = lines[lines.index('Port of Discharge')+1]
    except (ValueError, IndexError):
        raise CollectorError('MSC destination port could not be read.', code='destination_missing')
    if location(port) not in {location(p) for p in NIGERIAN_PORTS}:
        raise CollectorError('MSC returned an unsupported discharge port; destination review is needed.', code='destination_unsupported')
    return port


def parse(text, bl, destination=None, today=None):
    today = today or dt.datetime.now(ZoneInfo('Africa/Lagos')).date().isoformat()
    if not isinstance(text, str) or len(text) > 2*1024*1024:
        raise CollectorError('MSC returned an oversized or unreadable page.')
    lines = [re.sub(r'\s+', ' ', s).strip() for s in text.splitlines() if s.strip()]
    title = next((s for s in lines if s.startswith('BILL OF LADING:')), '')
    if title.partition(':')[2].strip().upper() != bl:
        raise CollectorError('Returned Bill of Lading does not match this job.')
    port = discover_destination(text)
    if destination is not None and location(port) != location(destination):
        raise CollectorError('MSC destination does not match the selected Nigerian port. Review the tracking setup.')
    if not re.search(r',\s*NG$', port, re.I):
        raise CollectorError('Only Nigerian destination tracking is supported in this pilot.')
    count_match = re.search(r'\(\s*(\d+)\s+Containers?\s*\)', ' '.join(lines))
    source_stamp = next((s for s in lines if s.startswith('Tracking results provided by MSC')), '')
    if not count_match or not source_stamp:
        raise CollectorError('Incomplete MSC results; container total/source timestamp is missing.')
    start = lines.index('CONTAINERS') if 'CONTAINERS' in lines else len(lines)
    end = lines.index(source_stamp)
    containers = []
    i = start+1
    while i < end:
        if lines[i] != 'Container' or i+1 >= end or not CONTAINER.fullmatch(lines[i+1]):
            i += 1
            continue
        number = lines[i+1]
        finish = next((j for j in range(i+2, end) if lines[j] == 'Container' and j+1 < end and CONTAINER.fullmatch(lines[j+1])), end)
        segment = lines[i+2:finish]
        events = []
        positions = [j for j, s in enumerate(segment) if DAY.fullmatch(s)]
        for n, j in enumerate(positions):
            stop = positions[n+1] if n+1 < len(positions) else len(segment)
            cells = segment[j:stop]
            # POD ETA in a header has no location/description columns; do not treat it as an actual event.
            if len(cells) < 3 or not re.search(r',\s*[A-Z]{2}$', cells[1]):
                continue
            event_date, place, label = calendar(cells[0]), cells[1], cells[2]
            normal = label.casefold()
            kind, actual = 'other', False
            if normal == 'estimated time of arrival' and location(place) == location(port):
                kind = 'eta'
            elif normal == 'import discharged from vessel' and location(place) == location(port):
                kind, actual = 'discharge', True
            elif normal in ('vessel berthed', 'vessel arrival', 'vessel arrived', 'actual time of arrival') and location(place) == location(port):
                kind, actual = 'berth', True
            elif normal == 'import to consignee' and location(place) == location(port):
                kind, actual = 'carrier_collection', True
            elif normal == 'empty received at cy' and re.search(r',\s*NG$', place, re.I):
                kind, actual = 'empty_return', True
            event = dict(date=event_date, raw_date=cells[0], location=place, label=label,
                         detail=cells[3:8], kind=kind, actual=actual, timezone=None)
            if actual and event_date > today:
                raise CollectorError('MSC reports a future actual event; review its date before applying.')
            event['id'] = hashlib.sha256(repr((number,event_date,place,label,cells[3:8])).encode()).hexdigest()
            events.append(event)
        if not events:
            raise CollectorError('A container history was collapsed or could not be read. No partial result was accepted.')
        if any(c['number'] == number for c in containers):
            raise CollectorError('MSC returned repeated container histories; review is required.')
        milestones = {}
        for key in ('eta', 'berth', 'discharge', 'carrier_collection', 'empty_return'):
            values = sorted({e['date'] for e in events if e['kind'] == key})
            if len(values) > 1:
                raise CollectorError('MSC returned conflicting '+key+' dates for a container.')
            milestones[key] = values[0] if values else None
        if milestones['empty_return']:
            if not (milestones['discharge'] and milestones['carrier_collection'] and
                    milestones['discharge'] <= milestones['carrier_collection'] <= milestones['empty_return']):
                # Keep evidence but never infer a destination empty return from an export/depot event.
                milestones['empty_return'] = None
        containers.append(dict(number=number, events=events, milestones=milestones))
        i = finish
    if not containers or len(containers) != int(count_match[1]):
        raise CollectorError('Container histories do not cover the MSC container total. Review is required.')
    aggregate = {}
    for key in ('eta', 'berth', 'discharge', 'empty_return'):
        values = [c['milestones'][key] for c in containers]
        # Actual job dates require evidence for every container, using the last event date.
        aggregate[key] = max(values) if all(values) else None
    return dict(parser=PARSER, carrier='MSC', bl=bl, destination=port, source_url=URL,
                source_timestamp=source_stamp, containers=containers, container_count=len(containers),
                milestones=aggregate, returned_count=sum(bool(c['milestones']['empty_return']) for c in containers),
                discharged_count=sum(bool(c['milestones']['discharge']) for c in containers))


def changes(previous, current):
    prior = {e['id'] for c in (previous or {}).get('containers', []) for e in c['events']}
    now = {e['id'] for c in current['containers'] for e in c['events']}
    return dict(new_events=sorted(now-prior), removed_events=sorted(prior-now),
                milestones=[dict(field=k,before=(previous or {}).get('milestones', {}).get(k),after=v)
                            for k,v in current['milestones'].items()
                            if (previous or {}).get('milestones', {}).get(k) != v])
