/** Execute actual TNQD component methods with controlled HTTP/permission dependencies.
 * This is a component-method harness, not an Angular-render or Java-backend test.
 */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createRequire } = require('node:module');
const workspace = path.resolve(process.argv[2]);
const req = createRequire(path.join(workspace, 'package.json'));
const ts = req('typescript'), rx = req('rxjs'), operators = req('rxjs/operators'), dates = req('date-fns');
const sourceDir = path.join(workspace, 'src/app/modules/military-youth/membership-roster/components/membership-list');
const source = fs.readFileSync(path.join(sourceDir, 'membership-list.component.ts'), 'utf8');
const template = fs.readFileSync(path.join(sourceDir, 'membership-list.component.html'), 'utf8');
const suites = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const output = process.argv[4];
const ast = ts.createSourceFile('component.ts', source, ts.ScriptTarget.Latest, true);
const klass = ast.statements.find(s => ts.isClassDeclaration(s) && s.name?.text === 'MembershipListComponent');
if (!klass) throw new Error('TNQD component class missing');
const clean = mods => mods?.filter(m => !ts.isDecorator(m) && ![ts.SyntaxKind.ExportKeyword, ts.SyntaxKind.DefaultKeyword].includes(m.kind));
const members = klass.members.map(m => {
  if (ts.isPropertyDeclaration(m)) return ts.factory.updatePropertyDeclaration(m, clean(m.modifiers), m.name, m.questionToken ?? m.exclamationToken, m.type, m.initializer);
  if (ts.isMethodDeclaration(m)) return ts.factory.updateMethodDeclaration(m, clean(m.modifiers), m.asteriskToken, m.name, m.questionToken, m.typeParameters, m.parameters, m.type, m.body);
  return m;
});
const stripped = ts.factory.updateClassDeclaration(klass, clean(klass.modifiers), klass.name, undefined, undefined, members);
const printer = ts.createPrinter();
const text = printer.printNode(ts.EmitHint.Unspecified, stripped, ast);
const compiled = ts.transpileModule(text, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
function signal(initial) { let current = initial; const getter = () => current; getter.set = x => { current = x; }; return getter; }
function control(value) { return { value, valueChanges: new rx.Subject(), setValue(next, options = {}) { this.value = next; if (options.emitEvent !== false) this.valueChanges.next(next); } }; }
function form(initial = {}) {
  const defaults = { keyword: '', idNumber: '', name: '', positions: [], governmentPositions: [], youthMemberTypes: [], statuses: [], youthUnionIds: null, fromDate: null, toDate: null, sortField: '', direction: '', youthUnionName: null, ...initial };
  const controls = Object.fromEntries(Object.entries(defaults).map(([k, v]) => [k, control(v)]));
  return { controls, invalid: false, get: key => controls[key], getRawValue: () => Object.fromEntries(Object.entries(controls).map(([k, c]) => [k, c.value])), markAllAsTouched() {}, updateValueAndValidity() {}, patchValue(values, options) { for (const [k, v] of Object.entries(values)) controls[k]?.setValue(v, options); }, reset() { for (const c of Object.values(controls)) c.setValue(null, { emitEvent: false }); } };
}
function setup() {
  const context = vm.createContext({ ...rx, ...operators, ...dates, signal, inject: () => undefined,
    takeUntilDestroyed: () => x => x, setTimeout, clearTimeout, console: { log() {}, warn() {}, error() {} },
    document: { addEventListener() {}, removeEventListener() {} }, window: {},
    YouthMemberType: { UNION_CADRE: 'UNION_CADRE' }, YouthStatus: {}, COMMON_LIMIT_INPUT: 255 });
  const Component = vm.runInContext(compiled + '\nMembershipListComponent;', context);
  const instance = Object.create(Component.prototype);
  instance.transloco = { translate: value => value };
  context.__instance = instance;
  for (const member of klass.members) {
    if (!ts.isPropertyDeclaration(member) || !member.initializer) continue;
    const key = member.name.getText(ast);
    if (!/^\w+$/.test(key)) continue;
    const init = member.initializer.getText(ast);
    try {
      const code = ts.transpileModule('const __value = (' + init + ');', { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText.replace(/^const __value = /, 'return ');
      instance[key] = vm.runInContext('(function(){' + code + '}).call(__instance)', context);
    } catch { /* Framework-only field dependencies are provided explicitly below. */ }
  }
  const calls = [], alerts = [], permissionResolvers = [];
  Object.assign(instance, { pageIndex: 0, pageSize: 20, total: 0, isLoading: false, listOfData: [], lastAppliedQuery: {}, columns: [],
    isAdvanceFilter: false, destroyRef: {}, searchForm: form(),
    cdr: { markForCheck() {}, detectChanges() {} },
    alertService: { createAlert(...args) { alerts.push(args); }, showHttpError(error) { alerts.push(error); } },
    service: { getMembershipRosterData(query) { const subject = new rx.Subject(); calls.push({ query: structuredClone(query), subject }); return subject; } },
    authz: { can: action => ['view', 'read', 'xem'].includes(action), loadObjectPermissions() { if (instance.deferPermissions) return new Promise(resolve => permissionResolvers.push(resolve)); return Promise.resolve(); } },
    R: { THONG_TIN_DOAN_VIEN: { KEY: 'thong_tin_doan_vien' } },
    route: { queryParams: rx.of({}) }, fb: { group: () => instance.searchForm },
    initCurrentYouth() {}, loadCategoryOptions() {}, calculateTableHeight() {}, applyColumnTemplates() {} });
  const respond = (request, names, total = names.length) => { request.subject.next({ detail: { content: names.map((name, i) => ({ id: i + 1, name })), totalElements: total } }); request.subject.complete(); };
  return { c: instance, calls, alerts, permissionResolvers, respond };
}
const results = [];
async function check(testcase) {
  const { c, calls, alerts, permissionResolvers, respond } = setup();
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  const id = testcase.id;
  if (['AC01', 'AC02', 'AC10'].includes(id)) {
    c.search(); respond(calls.at(-1), ['initial']); await wait(0);
    c.pageIndex = 2;
    if (id === 'AC02') { c.isAdvanceFilter = true; c.searchForm.get('name').setValue('DEMO-AN', { emitEvent: false }); c.search(); }
    else if (id === 'AC01') { c.ngOnInit(); c.pageIndex = 2; c.searchForm.get('keyword').setValue('DEMO-AN'); await wait(330); }
    else { c.searchForm.get('keyword').setValue('DEMO-BINH', { emitEvent: false }); c.search(); }
    assert(calls.at(-1).query.page === testcase.expected_page, 'Truy vấn mới chưa về trang đầu: page=' + calls.at(-1).query.page);
  } else if (id === 'AC03') {
    c.search(); respond(calls.at(-1), ['initial']); await wait(0); c.onPageChange(1);
    assert(calls.at(-1).query.page === testcase.expected_page, 'Chuyển trang chủ động bị reset');
  } else if (id === 'AC04') {
    c.pageIndex = 2; c.pageSizeChange(10);
    assert(calls.at(-1).query.page === 0 && calls.at(-1).query.size === testcase.expected_size, 'Đổi kích thước chưa đúng');
  } else if (id === 'AC09') {
    c.pageIndex = 2; c.searchForm.get('keyword').setValue('DEMO-AN', { emitEvent: false }); c.resetSearchForm();
    assert(calls.at(-1).query.page === testcase.expected_page && !calls.at(-1).query.keyword, 'Đặt lại bộ lọc chưa phục hồi trang đầu');
  } else if (id === 'AC06-HTTP') {
    c.searchForm.get('keyword').setValue('DEMO-AN', { emitEvent: false }); c.search(); const a = calls.at(-1);
    c.searchForm.get('keyword').setValue('DEMO-BINH', { emitEvent: false }); c.search(); const b = calls.at(-1);
    respond(b, ['DEMO-BINH'], 4); await wait(0); respond(a, ['DEMO-AN'], 3); await wait(0);
    assert(c.listOfData[0]?.name === testcase.expected_name && c.total === testcase.expected_total, 'Phản hồi HTTP cũ ghi đè truy vấn mới');
  } else if (id === 'AC06-PERMISSION') {
    c.deferPermissions = true;
    c.searchForm.get('keyword').setValue('DEMO-AN', { emitEvent: false }); c.search(); respond(calls.at(-1), ['DEMO-AN'], 3);
    c.searchForm.get('keyword').setValue('DEMO-BINH', { emitEvent: false }); c.search(); respond(calls.at(-1), ['DEMO-BINH'], 4);
    assert(permissionResolvers.length === 2, 'Không nhận đủ hai tác vụ tải quyền');
    permissionResolvers[1](); await wait(0); permissionResolvers[0](); await wait(0);
    assert(c.listOfData[0]?.name === testcase.expected_name && c.total === testcase.expected_total, 'Promise quyền cũ ghi đè truy vấn mới');
  } else if (id === 'AC05-CURRENT-LOADING') {
    c.searchForm.get('keyword').setValue('DEMO-AN', { emitEvent: false }); c.search(); const a = calls.at(-1);
    c.searchForm.get('keyword').setValue('DEMO-BINH', { emitEvent: false }); c.search(); respond(a, []); await wait(0);
    assert(c.isLoading === true, 'Request cũ đã tắt loading của request mới');
  } else if (id === 'AC05') {
    c.search(); assert(c.isLoading === true, 'Không bật loading khi chờ');
    assert(!/\[loading\]\s*=\s*["']false["']/.test(template), 'Template chưa nối loading thực');
    respond(calls.at(-1), []); await wait(0); assert(c.isLoading === false, 'Loading không kết thúc');
  } else if (id === 'AC07') {
    c.search(); respond(calls.at(-1), [], 0); await wait(0);
    assert(c.listOfData.length === 0 && c.total === 0 && alerts.length === 0, 'Danh sách rỗng bị xử lý thành lỗi');
  } else if (id === 'AC08') {
    c.search(); calls.at(-1).subject.error({ status: 500, error: { detail: { name: 'Lỗi đọc dữ liệu demo' } } }); await wait(0);
    assert(c.isLoading === false && alerts.length > 0, 'Lỗi đọc không được báo/kết thúc loading');
    c.search(); respond(calls.at(-1), ['retry']); await wait(0); assert(c.listOfData[0]?.name === 'retry', 'Không thử lại được');
  } else if (id === 'AC11') {
    c.search(); respond(calls.at(-1), ['readonly']); await wait(0);
    assert(c.authz.can('sua') === false && c.authz.can('xoa') === false && c.listOfData.length === 1, 'Fixture chỉ đọc không giữ được hành vi');
  } else throw new Error('Không có interpreter được duyệt cho testcase ' + id);
}
(async () => {
  for (const testcase of suites.cases) {
    if (testcase.id === 'AC12-BROWSER') continue;
    try { await check(testcase); results.push({ id: testcase.id, label: testcase.title, status: 'PASS' }); }
    catch (error) { results.push({ id: testcase.id, label: testcase.title, status: 'FAIL', error: String(error.message).slice(0, 1000) }); }
  }
  const result = { kind: 'REAL_TYPESCRIPT_COMPONENT_METHODS_WITH_CONTROLLED_DEPENDENCIES', source_sha256: require('node:crypto').createHash('sha256').update(source).digest('hex'), tests: results, total: results.length, passed: results.filter(r => r.status === 'PASS').length, backend_java_verified: false, browser_verified: false };
  fs.writeFileSync(output, JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ total: result.total, passed: result.passed, failed: result.total-result.passed }));
  process.exitCode = result.passed === result.total ? 0 : 1;
})().catch(error => { console.error(error); process.exitCode = 2; });
