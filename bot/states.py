from aiogram.fsm.state import State, StatesGroup

class ThumbStates(StatesGroup):
    choosing_action = State()
    waiting_timestamp = State()
    waiting_photo = State()
