"""Apply an extracted layout to complete captured results, without template data."""

import re

from .workbooks import NUMERIC_TYPES, ReportDataError, excel_number
from .currencies import display_currency

FORMATS = {'decimal': '#,##0.00;[Red](#,##0.00);"—"',
           'integer': '#,##0;[Red](#,##0);"—"',
           'percent': '0.00%;(0.00%);"—"'}


def reference_table(book, sheet, reference, source, item, row):
    profile = next((p for p in reference.get('sheet_layouts', []) if p['name'] == item['reference_sheet']), None)
    if not profile:
        raise ReportDataError('Reference sheet layout is unavailable. Inspect the uploaded format reference first.')
    fields = item.get('columns') or source['fields']
    if (not fields or len(set(fields)) != len(fields) or set(fields)-set(source['fields'])
            or len(fields) != len(profile['column_widths'])):
        raise ReportDataError('Reference columns must map one-to-one to the captured dataset; do not drop or invent fields to fit a template.')
    headers = item['headers']
    if (not isinstance(headers,list) or len(headers) != len(profile['headers']) or
            any(not isinstance(level,list) or len(level) != len(fields) or
                any(value is not None and (not isinstance(value,str) or len(value)>300) for value in level) for level in headers)):
        raise ReportDataError('Author every header level with the reference dimensions, in Albanian and for the requested period. Use None for merged children.')
    for expected, actual in zip(profile['headers'],headers):
        if any(label not in (None,'') and (value is None or not value.strip()) for label,value in zip(expected,actual)):
            raise ReportDataError('Every populated reference header needs an authored current-period label.')
    formats = item.get('formats') or {}
    if not isinstance(formats,dict) or set(formats)-set(fields) or any(v not in FORMATS for v in formats.values()):
        raise ReportDataError('Choose decimal, integer or percent formats for actual source fields.')
    start = profile['start_column']
    styles = reference['styles']
    cache = {}

    def format_for(identifier, field=None):
        key = (identifier, formats.get(field))
        if key not in cache:
            options = dict(styles[identifier])
            if field in formats:
                options['num_format'] = FORMATS[formats[field]]
            if options.get('font_color','').upper()=='#FFFFFF' and options.get('bg_color'):
                options['num_format'] = options.get('num_format','General').replace('[Red]','')
            cache[key] = book.add_format(options)
        return cache[key]

    if start:
        sheet.set_column(0,start-1,3)
    widths = list(profile['column_widths'])
    for c,width in enumerate(widths,start):
        sheet.set_column(c,c,width)
    occupied = set()
    for r1,c1,r2,c2 in profile['merges']:
        for r in range(r1,r2+1):
            for c in range(c1,c2+1):
                if (r,c) != (r1,c1) and headers[r][c] not in (None,''):
                    raise ReportDataError('A merged header would hide another label. Leave merged child headers empty.')
                occupied.add((r,c))
        sheet.merge_range(row+r1,start+c1,row+r2,start+c2,headers[r1][c1] or '',
                          format_for(profile['header_styles'][r1][c1]))
    for r,level in enumerate(headers):
        sheet.set_row(row+r,profile['header_heights'][r])
        for c,value in enumerate(level):
            if (r,c) not in occupied:
                sheet.write(row+r,start+c,value,format_for(profile['header_styles'][r][c]))
    first = row+len(headers)
    if first+len(source['rows'])>1048500:
        raise ReportDataError('Reference output exceeds Excel worksheet capacity.')
    row_profiles = {str(p['label']).strip().casefold():p for p in profile['body_rows']}
    for offset, values in enumerate(source['rows'],first):
        matched = row_profiles.get(str(values.get(fields[0],'')).strip().casefold())
        row_styles = matched['styles'] if matched else profile['body_styles']
        sheet.set_row(offset, matched['height'] if matched else 24)
        for c,field in enumerate(fields):
            value = display_currency(values.get(field)) if field in source['currency_columns'] else values.get(field)
            numeric = excel_number(value,True) if source['types'].get(field) in NUMERIC_TYPES or isinstance(value,(int,float)) and not isinstance(value,bool) else None
            if numeric is None and isinstance(value,(int,float)) and not isinstance(value,bool):
                value = str(value)
            sheet.write(offset,start+c,numeric if numeric is not None else value,format_for(row_styles[c],field))
            if numeric is not None:
                code = FORMATS.get(formats.get(field),styles[row_styles[c]].get('num_format','General'))
                decimals = re.search(r'\.([0#]+)',code)
                places = min(6,len(decimals[1])) if decimals else 0
                displayed = format(numeric,f'.{places}%') if '%' in code else format(numeric,f',.{places}f')
                widths[c] = min(60,max(widths[c],len(displayed)+2))
    for c,width in enumerate(widths,start):
        sheet.set_column(c,c,width)
    sheet.freeze_panes(first,start+profile['freeze_columns'])
    sheet.repeat_rows(row,first-1)
    if profile['landscape']:
        sheet.set_landscape()
    else:
        sheet.set_portrait()
    sheet.set_zoom(min(120,max(60,profile['zoom'])))
    sheet.fit_to_pages(1,0)
    # The model can append notes; the caller extends this area afterward.
    return first+len(source['rows'])+2, {'kind':'table','sheet':sheet.name,'row':first+1,
            'column':start+1,'request':{**item,'currency':None},'row_count':len(source['rows'])}
