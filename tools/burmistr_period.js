// Выбор периода в фильтре Бурмистра (календарь react-date-range) без кликов мышью.
// Выполняется в странице через javascript_tool. Пример в конце файла.
async function burmistrPeriod(label, from, to) {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const months = ['янв', 'фев', 'мар', 'апр', 'ма', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
  const press = el => ['mousedown', 'mouseup', 'click'].forEach(t =>
    el.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window })));

  // Поле фильтра: ищем подпись (например «Дата документа») и ближайшее поле ввода после неё.
  const caption = [...document.querySelectorAll('body *')]
    .find(e => e.children.length === 0 && e.innerText && e.innerText.trim() === label);
  if (!caption) throw new Error('Не найдено поле «' + label + '»');
  let box = caption.parentElement, input = null;
  for (let i = 0; i < 4 && !input; i++, box = box.parentElement) input = box.querySelector('input');
  if (!input) throw new Error('Нет поля ввода у «' + label + '»');
  input.focus(); press(input); await sleep(500);

  const cal = () => document.querySelector('.calendar-container.shown');
  if (!cal()) throw new Error('Календарь не открылся');
  const shown = () => {  // какой месяц сейчас открыт: «окт. 2026» → {m: 9, y: 2026}
    const t = cal().querySelector('.rdrMonthName').innerText.trim().toLowerCase();
    return { m: months.findIndex(p => t.startsWith(p)), y: +t.match(/\d{4}/)[0] };
  };
  const goTo = async d => {
    for (let i = 0; i < 24; i++) {
      const s = shown(), diff = (d.getFullYear() - s.y) * 12 + (d.getMonth() - s.m);
      if (diff === 0) return;
      press(cal().querySelector(diff < 0 ? '.rdrPprevButton' : '.rdrNextButton')); await sleep(300);
    }
    throw new Error('Не удалось перейти к месяцу');
  };
  const pick = async d => {
    await goTo(d);
    const btn = [...cal().querySelectorAll('button.rdrDay:not(.rdrDayPassive)')]
      .find(b => b.innerText.trim() === String(d.getDate()));
    if (!btn) throw new Error('Нет дня ' + d.getDate());
    press(btn); await sleep(400);
  };
  await pick(from);
  await pick(to);
  return input.value;  // должно быть «дд.мм.гггг - дд.мм.гггг»
}

// Пример: последние 7 дней по «Дата документа»
// const to = new Date(), from = new Date(Date.now() - 7 * 864e5);
// await burmistrPeriod('Дата документа', from, to);
