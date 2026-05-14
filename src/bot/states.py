from aiogram.fsm.state import State, StatesGroup


class AnalysisStates(StatesGroup):
    waiting_file = State()
    waiting_context = State()
    analyzing = State()
