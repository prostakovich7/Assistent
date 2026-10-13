Создай ОДНУ задачу в CRM «Бурмистр» (https://kv.burmistr.ru) по поручению директора. Работай через Claude in Chrome (инструменты mcp__claude-in-chrome__*). Вход в Бурмистр выполнен.

Поручение лежит в файле: {TASK_FILE}
Прочитай его (Read). Поля: assignee — ФИО исполнителя, text — суть поручения, deadline — срок ГГГГ-ММ-ДД (может быть пустым), letter_number — номер входящего письма, letter_id — его идентификатор в Бурмистре (оба пустые, если задача без письма).

ПРАВИЛА
- Создаёшь ровно одну задачу — ту, что в файле. Больше ничего в Бурмистре не меняешь.
- Вкладка Chrome скрыта: настоящие клики не работают. Всё делай через javascript_tool. Скриншоты не делай.
- Работай в одной своей новой вкладке (tabs_context_mcp с createIfEmpty, затем tabs_create_mcp) и закрой её в конце.
- Прочитай файл C:\Users\user\Downloads\Assistent\tools\burmistr_task.js — там функция burmistrFillTask({title, assignees, deadline, text}), которая заполняет форму скриптом. Её текст нужно выполнить в странице через javascript_tool вместе с вызовом.

ШАГИ
1. Если letter_id НЕ пустой (задача по письму):
   а) Открой https://kv.burmistr.ru/correspondence#t:c=i:e&i:e:target=<letter_id>, подожди 7 секунд. Проверь, что в карточке номер входящего = letter_number.
   б) Нажми в карточке «Создать задачу» скриптом, заглушив всплывающее окно:
      window.open = () => null; const b=[...document.querySelectorAll('button')].find(x=>x.innerText.trim()==='Создать задачу'); const k=Object.keys(b).find(k=>k.startsWith('__reactProps')); b[k].onClick({preventDefault(){},stopPropagation(){},target:b,currentTarget:b,nativeEvent:new MouseEvent('click')});
      Подожди 2 секунды.
   в) В ЭТОЙ ЖЕ вкладке открой https://kv.burmistr.ru/tasks/add?&sourceType=correspondence&sourceId=<letter_id>, подожди 6 секунд. Название задачи должно быть «Задача по Вх. <letter_number>», в описании — текст письма. Если не так — не продолжай, запиши ошибку (шаг 5).
   г) Выполни burmistrFillTask({assignees: [assignee], deadline, text}) — название НЕ передавай (оставь «Задача по Вх. N»).
2. Если letter_id пустой (задача без письма):
   Открой https://kv.burmistr.ru/tasks/add, подожди 6 секунд и выполни burmistrFillTask({title: <короткое название из text, до 80 знаков>, assignees: [assignee], deadline, text}).
3. Проверь отчёт функции: исполнитель — фамилия assignee; срок — нужная дата (или пусто, если deadline пустой); описание начинается с «"КК"». Если что-то не так — не создавай, запиши ошибку.
4. Нажми «Добавить» скриптом:
   const b=[...document.querySelectorAll('button')].find(x=>x.innerText.trim()==='Добавить'); const k=Object.keys(b).find(k=>k.startsWith('__reactProps')); if (k && b[k].onClick) b[k].onClick({preventDefault(){},stopPropagation(){},target:b,currentTarget:b,nativeEvent:new MouseEvent('click')}); else b.click();
   Подожди 5 секунд. Узнай номер созданной задачи: по адресу страницы, заголовку или тексту страницы (номер задачи — 4–5 цифр). Если не видно — открой https://kv.burmistr.ru/tasks, вкладку «Я создал», и найди самую новую задачу с этим исполнителем и текстом. Если задача не создалась (форма осталась с ошибкой) — запиши текст ошибки со страницы.
5. Запиши результат в файл {RESULT_FILE} (Write) — только JSON:
   {"ok": true, "task_number": "6380"}  или  {"ok": false, "error": "коротко, что пошло не так"}
6. Закрой свою вкладку. Ответь одной строкой.
