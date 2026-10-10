// Casos ficticios: colores que pinta la web (buildFastViewColorFn) para cada elemento.
// Genera tests/colores_web.json, que usa test_colores_web.py. Para regenerarlo, desde el
// frontal (con sus dependencias instaladas), empaquetar la función y correr este guion:
//   node_modules/.bin/esbuild entrada.js --bundle --format=esm --platform=node \
//     --alias:src=./src --alias:utils=./src/utils --outfile=web.mjs
//   (entrada.js: export { buildFastViewColorFn } from './src/components/mapComponents/viewStyleProcessor.js')
//   node colores_web.mjs ../geosian-qgis-plugin/tests/colores_web.json
import { buildFastViewColorFn } from './web.mjs';
import { writeFileSync } from 'node:fs';

const R = [230, 25, 75], V = [60, 180, 75], A = [0, 130, 200], M = [255, 225, 25, 200];
const casos = [
  {
    nombre: 'graduado con colores, sin color para el último tramo y con default',
    config: { mode: 'graduated', color: { mode: 'graduated', attribute: 'altura',
      breaks: [0, 10, 20, 30], colors: [R, V, A].slice(0, 2), default: { color: [10, 20, 30, 230] } } },
    elementos: [{ altura: -5 }, { altura: 0 }, { altura: 5 }, { altura: 10 }, { altura: 25 },
      { altura: 30 }, { altura: 99 }, { altura: null }, {}, { altura: 'abc' }, { altura: '12' }],
  },
  {
    nombre: 'graduado con colores y sin default',
    config: { mode: 'graduated', color: { mode: 'graduated', attribute: 'altura',
      breaks: [0, 10], colors: [R, A] } },
    elementos: [{ altura: 3 }, { altura: 50 }, { altura: null }, {}, { altura: 'n/d' }],
  },
  {
    nombre: 'graduado con rampa continua',
    config: { mode: 'graduated', color: { mode: 'graduated', attribute: 'altura',
      breaks: [0, 40, 100], colorRamp: 'viridis' } },
    elementos: [{ altura: -10 }, { altura: 0 }, { altura: 12.5 }, { altura: 25 }, { altura: 50 },
      { altura: 62.5 }, { altura: 99 }, { altura: 100 }, { altura: 150 }, { altura: null }, {}],
  },
  {
    nombre: 'reglas: orden, nulos, sin color, operador desconocido y filtro vacío',
    config: { mode: 'rule_based', color: { mode: 'rule_based', rules: [
      { name: 'Altos', filter: { operator: 'and', rules: [{ field: 'altura', operator: '>', value: 5 }] }, style: { color: R } },
      { name: 'Tilos', filter: { rules: [{ field: 'tipo', operator: 'equals', value: 'Tilo' }] }, style: { color: A } },
      { name: 'Con pl', filter: { operator: 'or', rules: [
        { field: 'tipo', operator: 'operador_nuevo', value: 1 },
        { field: 'tipo', operator: 'contains', value: 'PL' }] }, style: { color: V } },
      { name: 'Sin color', filter: { rules: [{ field: 'tipo', operator: 'starts_with', value: 'ol' }] }, style: {} },
      { name: 'Sin filtro', style: { color: R } },
      { name: 'Todo', filter: { operator: 'and', rules: [] }, style: { color: M } },
    ] } },
    elementos: [{ altura: 7, tipo: 'Tilo' }, { altura: null, tipo: 'Tilo' }, { tipo: 'Tilo' },
      { tipo: 'Plátano' }, { tipo: 'Olmo' }, { tipo: 'Pino' }, {}],
  },
  {
    nombre: 'reglas: todos los operadores, sin else',
    config: { mode: 'rule_based', color: { mode: 'rule_based', rules: [
      { name: 'in', filter: { rules: [{ field: 'tipo', operator: 'in', value: ['Haya', 'Roble'] }] }, style: { color: [1, 0, 0] } },
      { name: 'between', filter: { rules: [{ field: 'altura', operator: 'between', value: [10, 20] }] }, style: { color: [2, 0, 0] } },
      { name: '>=', filter: { rules: [{ field: 'altura', operator: 'gte', value: 50 }] }, style: { color: [3, 0, 0] } },
      { name: '<', filter: { rules: [{ field: 'altura', operator: 'lt', value: 1 }] }, style: { color: [4, 0, 0] } },
      { name: '<=', filter: { rules: [{ field: 'altura', operator: '<=', value: 2 }] }, style: { color: [5, 0, 0] } },
      { name: 'ends', filter: { rules: [{ field: 'tipo', operator: 'ends_with', value: 'ÑO' }] }, style: { color: [6, 0, 0] } },
      { name: 'eq num', filter: { rules: [{ field: 'altura', operator: '=', value: '33' }] }, style: { color: [7, 0, 0] } },
      { name: 'vacío', filter: { rules: [{ field: 'nota', operator: 'is_empty' }] }, style: { color: [8, 0, 0] } },
      { name: 'not_in y !=', filter: { operator: 'and', rules: [
        { field: 'tipo', operator: 'not_in', value: ['Pino'] },
        { field: 'tipo', operator: 'neq', value: 'Abeto' },
        { field: 'nota', operator: 'is_not_empty' },
        { field: 'nota', operator: 'not_contains', value: 'seco' }] }, style: { color: [9, 0, 0] } },
    ] } },
    elementos: [{ tipo: 'Roble', altura: 3, nota: 'x' }, { tipo: 'Pino', altura: 15, nota: 'x' },
      { tipo: 'Pino', altura: 70, nota: 'x' }, { tipo: 'Pino', altura: 0.5, nota: 'x' },
      { tipo: 'Pino', altura: 2, nota: 'x' }, { tipo: 'Castaño', altura: 4, nota: 'x' },
      { tipo: 'Pino', altura: 33, nota: 'x' }, { tipo: 'Pino', altura: 40, nota: '' },
      { tipo: 'Fresno', altura: 40, nota: 'verde' }, { tipo: 'Fresno', altura: 40, nota: 'Seco' },
      { tipo: 'Abeto', altura: 40, nota: 'verde' }],
  },
  {
    nombre: 'reglas con else',
    config: { mode: 'rule_based', color: { mode: 'rule_based', else: { color: [11, 22, 33, 230] }, rules: [
      { name: 'Tilos', filter: { rules: [{ field: 'tipo', operator: 'eq', value: 'Tilo' }] }, style: { color: A } }] } },
    elementos: [{ tipo: 'Tilo' }, { tipo: 'Pino' }, {}],
  },
];

for (const caso of casos) {
  const { colorFn } = buildFastViewColorFn(caso.config);
  caso.colores = caso.elementos.map((p) => colorFn(p));
}
writeFileSync(process.argv[2], JSON.stringify({
  origen: 'buildFastViewColorFn de viewStyleProcessor.js, geosian-frontend main d7ea44e0',
  casos,
}, null, 1) + '\n');
