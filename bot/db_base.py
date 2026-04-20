"""SQLAlchemy declarative base, kept in its own module.

This lives outside `bot.database` to break the cycle flagged by CodeQL
(`py/cyclic-import`): `bot.database.init_db` needs to import `bot.models` to
register all tables with Base.metadata, and `bot.models` needs the same Base
to declare each ORM class. Hosting Base here means neither module has to
import the other at module level.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
