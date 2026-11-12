// Shows the rows of a table page by page (20 rows per page)
const PAGE_SIZE = 20;

function createPager(tableId, pagerId, pageSize = PAGE_SIZE) {
    const tbody = document.getElementById(tableId).getElementsByTagName('tbody')[0];
    const controls = document.getElementById(pagerId);
    let rows = [];
    let page = 1;

    function button(label, target, disabled) {
        const element = document.createElement('button');
        element.className = 'button button-small';
        element.textContent = label;
        element.disabled = disabled;
        element.addEventListener('click', () => { page = target; render(); });
        return element;
    }

    function render() {
        const pages = Math.max(1, Math.ceil(rows.length / pageSize));
        page = Math.min(Math.max(1, page), pages);
        tbody.replaceChildren(...rows.slice((page - 1) * pageSize, page * pageSize));
        controls.replaceChildren();
        if (pages === 1) return;
        const position = document.createElement('span');
        position.className = 'pager-position';
        position.textContent = `Seite ${page} von ${pages}`;
        controls.append(button('« Erste', 1, page === 1), button('‹ Zurück', page - 1, page === 1), position,
            button('Weiter ›', page + 1, page === pages), button('Letzte »', pages, page === pages));
    }

    return {
        // New content after a refresh: the current page is kept if it still exists
        setRows(newRows) { rows = newRows; render(); },
        firstPage() { page = 1; render(); }
    };
}
