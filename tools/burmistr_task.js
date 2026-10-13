// Заполнение формы «Новая задача» в Бурмистре (/tasks/add) скриптом, без кликов мышью —
// работает и в скрытой вкладке Chrome. Выполняется через javascript_tool.
// КНОПКУ «Добавить» ЭТОТ СКРИПТ НЕ НАЖИМАЕТ — это отдельный шаг.
async function burmistrFillTask({ title, assignees, deadline, text }) {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  const press = el => ['mousedown', 'mouseup', 'click'].forEach(t =>
    el.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window })));
  const reactClick = el => {
    const k = Object.keys(el).find(k => k.startsWith('__reactProps'));
    el[k].onClick({ preventDefault() {}, stopPropagation() {}, target: el, currentTarget: el,
                    nativeEvent: new MouseEvent('click') });
  };
  const setValue = (el, v) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const inputFor = label => {
    const cap = [...document.querySelectorAll('body *')]
      .find(e => e.children.length === 0 && e.innerText && e.innerText.trim() === label
                 && !e.closest('.react-browser-container'));
    if (!cap) throw new Error('Нет поля «' + label + '»');
    let box = cap.parentElement, el = null;
    for (let i = 0; i < 4 && !el; i++, box = box.parentElement) el = box.querySelector('input');
    return el;
  };
  const report = {};

  // Название: у задачи по письму Бурмистр уже подставил «Задача по Вх. N» — не трогаем.
  if (title) { setValue(inputFor('Название задачи'), title); }
  report.title = inputFor('Название задачи').value;

  // Срок: календарь react-datepicker, ставим день → время подставится 23:59.
  if (deadline) {
    const d = new Date(deadline + 'T12:00:00');
    const input = inputFor('Срок исполнения');
    input.focus(); press(input); await sleep(700);
    const months = ['январь','февраль','март','апрель','май','июнь','июль','август','сентябрь','октябрь','ноябрь','декабрь'];
    for (let i = 0; i < 24; i++) {
      const head = document.querySelector('.react-datepicker__current-month').innerText.toLowerCase();
      const m = months.findIndex(x => head.startsWith(x)), y = +head.match(/\d{4}/)[0];
      const diff = (d.getFullYear() - y) * 12 + (d.getMonth() - m);
      if (diff === 0) break;
      document.querySelector(diff < 0 ? '.react-datepicker__navigation--previous'
                                       : '.react-datepicker__navigation--next').click();
      await sleep(300);
    }
    const day = [...document.querySelectorAll('.react-datepicker__day:not(.react-datepicker__day--outside-month)')]
      .find(x => x.innerText.trim() === String(d.getDate()));
    if (!day) throw new Error('Нет дня ' + d.getDate() + ' в календаре');
    day.click(); await sleep(600);
    report.deadline = input.value;
  }

  // Исполнители: окно выбора → поиск по фамилии → строка → «Выбрать».
  const field = [...document.querySelectorAll('.browser-single-action')].find(f => /Исполнители/.test(f.innerText));
  report.assignees = [];
  for (const fio of assignees || []) {
    reactClick(field); await sleep(1500);
    const modal = [...document.querySelectorAll('.react-browser-container')].find(vis);
    if (!modal) throw new Error('Не открылось окно выбора исполнителей');
    const search = [...modal.querySelectorAll('input')].filter(vis)
      .find(i => /ФИО/.test(i.closest('div')?.parentElement?.innerText || '')) || [...modal.querySelectorAll('input[type=text]')].filter(vis)[0];
    setValue(search, fio.split(' ')[0]);
    const go = [...modal.querySelectorAll('button')].find(b => vis(b) && b.querySelector('svg') && !b.innerText.trim());
    if (go) go.click(); else search.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    await sleep(1500);
    const rows = [...modal.querySelectorAll('tr.browser-react-row')].filter(vis);
    const row = rows.find(r => r.innerText.startsWith(fio)) || rows.find(r => r.innerText.startsWith(fio.split(' ')[0]));
    if (!row) { [...modal.querySelectorAll('button')].find(b => b.innerText.trim() === 'Закрыть').click();
                throw new Error('Не найден сотрудник «' + fio + '»'); }
    press(row.querySelector('td') || row); await sleep(500);
    [...modal.querySelectorAll('button')].find(b => /^Выбрать/.test(b.innerText.trim())).click();
    await sleep(1200);
  }
  report.assignees = field.innerText.replace(/\s+/g, ' ').replace('Исполнители', '').replace('...', '').trim();

  // Описание: поручение директора с меткой «"КК"» в начале, ниже — то, что уже было (текст письма).
  if (text) {
    const ed = document.querySelector('.ql-editor');
    const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
    const old = ed.classList.contains('ql-blank') ? '' : ed.innerHTML;
    ed.innerHTML = '<p>"КК" ' + esc(text) + '</p>' + (old ? '<p><br></p>' + old : '');
    await sleep(500);
    report.description = ed.innerText.slice(0, 200);
  }
  return report;
}
