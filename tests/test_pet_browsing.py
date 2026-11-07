"""Pet pagination and browse lifetime checks without Telegram or a database."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock


class PetBrowsingTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'main.py').read_text())
        names = {'_pet_list_markup', '_pet_picker_rows', 'pet_cmd', 'pethub_cmd'}
        nodes = [n for n in tree.body if
                 isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names
                 or isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and
                     t.id in {'_PET_PICKER_PER_PAGE', '_PET_BROWSE_TIMEOUT'} for t in n.targets)]
        self.env = dict(InlineKeyboardButton=lambda text, callback_data: SimpleNamespace(
            text=text, callback_data=callback_data), InlineKeyboardMarkup=lambda rows: rows,
            PET_SPECIES={}, _pet_display_name=lambda pet: str(pet['pet_id']),
            _pet_iv_pct=lambda pet: 50, Update=object,
            ContextTypes=SimpleNamespace(DEFAULT_TYPE=object))
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'main.py', 'exec'), self.env)
        self.pets = [dict(pet_id=i) for i in range(45)]

    def list_buttons(self, page):
        rows = self.env['_pet_list_markup'](self.pets, page, uid=42)
        return [b.callback_data for row in rows for b in row]

    def test_twenty_pets_and_correct_navigation(self):
        for page, count in [(0, 20), (1, 20), (2, 5)]:
            buttons = self.list_buttons(page)
            ids = [int(b.split('_')[1]) for b in buttons if b.startswith('petview_')]
            self.assertEqual(ids, list(range(page*20, page*20+count)))
            self.assertEqual(f'petlist_{page-1}' in buttons, page > 0)
            self.assertEqual(f'petlist_{page+1}' in buttons, page < 2)

    def test_stale_page_clamps_after_pets_removed(self):
        self.assertEqual(self.list_buttons(99), self.list_buttons(2))
        self.assertEqual(self.list_buttons(-1), self.list_buttons(0))

    def test_trade_and_gift_pickers_show_twenty(self):
        rows, page, total = self.env['_pet_picker_rows'](
            self.pets, 1, lambda pt: f"pick_{pt['pet_id']}", 'page_{page}')
        self.assertEqual((page, total), (1, 3))
        self.assertEqual([b.callback_data for row in rows for b in row
                          if b.callback_data.startswith('pick_')],
                         [f'pick_{i}' for i in range(20, 40)])

    def test_pet_and_hub_allow_thirty_minutes_in_groups_and_dms(self):
        for command in ['pet_cmd', 'pethub_cmd']:
            for chat_id in [42, -100123]:
                with self.subTest(command=command, chat_id=chat_id):
                    delete = Mock(return_value=object())
                    task = Mock()
                    self.env.update(get_player=lambda uid: {'username': 'Alice'},
                        get_active_pet_record=lambda uid: None,
                        _pet_run_autonomous=AsyncMock(return_value=None),
                        _build_pet_home=lambda uid, p: ('Pets', []),
                        _pethub_markup=lambda *args, **kwargs: [],
                        _auto_delete=delete, asyncio=SimpleNamespace(create_task=task))
                    update = SimpleNamespace(effective_user=SimpleNamespace(id=42),
                        effective_chat=SimpleNamespace(id=chat_id),
                        message=SimpleNamespace(delete=AsyncMock()))
                    bot = SimpleNamespace(send_message=AsyncMock(
                        return_value=SimpleNamespace(message_id=7)))
                    asyncio.run(self.env[command](update, SimpleNamespace(bot=bot)))
                    delete.assert_called_once_with(bot, chat_id, 7, 1800)
                    task.assert_called_once()


if __name__ == '__main__':
    unittest.main()
