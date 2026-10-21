import fs from 'node:fs/promises';
import {Workbook} from '@oai/artifact-tool';
const root='/home/pume-laptop/Documents/duka-group/duka-report-ai-agent-v3/outputs/report-reference-20261021';
// Render cached source values and inspected formatting, avoiding recalculation
// of the office workbook's entire external/formula graph. Never export a copy.
for(const item of JSON.parse(await fs.readFile(`${root}/visual-inputs.json`,'utf8'))){
 const wb=Workbook.create();const s=wb.worksheets.add('Performanca');s.showGridLines=false;
 s.getRange('A1:M20').values=item.values;
 for(const f of item.formats){
  const r=s.getRange(f.address);r.format.font=f.font;
  if(f.fill)r.format.fill=f.fill;
  r.setNumberFormat(f.number_format);r.format.wrapText=!!f.wrap;
  if(['left','center','right'].includes(f.align))r.format.horizontalAlignment=f.align;
  r.format.verticalAlignment='center';
 }
 for(const [col,width] of Object.entries(item.widths))s.getRange(`${col}1:${col}20`).format.columnWidth=width;
 for(const [row,height] of Object.entries(item.heights))s.getRange(`A${row}:M${row}`).format.rowHeight=height;
 for(const merge of item.merges)s.mergeCells(merge);
 const preview=await wb.render({sheetName:'Performanca',range:'A1:M18',scale:1,format:'png'});
 await fs.writeFile(`${root}/${item.name}.png`,new Uint8Array(await preview.arrayBuffer()));
 console.log(`Rendered ${item.name}`);
}
