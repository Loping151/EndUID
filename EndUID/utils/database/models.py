"""EndUID 数据库模型"""
import time
from typing import Optional, Type

from sqlmodel import Field, select, col
from datetime import datetime

from sqlalchemy import Index, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import and_, or_

from gsuid_core.utils.database.base_models import (
    Bind,
    User,
    BaseModel,
    BaseBotIDModel,
    with_session,
)
from gsuid_core.utils.database.models import Subscribe
from gsuid_core.webconsole.mount_app import site, GsAdminModel, PageSchema



class EndBind(Bind, table=True):
    """终末地 UID 绑定表"""

    __tablename__ = "EndBind"
    __table_args__ = {"extend_existing": True}
    
    # 终末地 UID
    uid: Optional[str] = Field(
        default=None,
        title="终末地 UID"
    )

    @classmethod
    async def insert_end_uid(
        cls,
        user_id: str,
        bot_id: str,
        uid: str,
        group_id: Optional[str] = None,
        length_limit: Optional[int] = None,
    ) -> int:
        """插入或更新 UID 绑定（复用基类逻辑）"""
        return await cls.insert_uid(
            user_id=user_id,
            bot_id=bot_id,
            uid=uid,
            group_id=group_id,
            lenth_limit=length_limit,
            is_digit=True,
        )

    @classmethod
    async def get_data_by_user_id(
        cls,
        user_id: str,
        bot_id: str,
    ) -> Optional["EndBind"]:
        """按用户与 bot 获取绑定记录"""
        return await cls.select_data(user_id, bot_id)

    @classmethod
    async def get_bound_uid(
        cls,
        user_id: str,
        bot_id: str,
    ) -> Optional[str]:
        """根据用户获取当前绑定的 UID（第一个）

        Args:
            user_id: QQ 用户 ID
            bot_id: Bot ID

        Returns:
            当前绑定的 UID，如果没有绑定返回 None
        """
        data = await cls.get_data_by_user_id(user_id, bot_id)
        if data is None or not data.uid:
            return None

        uid_list = data.uid.split('_')
        return uid_list[0] if uid_list else None

    @classmethod
    async def get_all_uids(
        cls,
        user_id: str,
        bot_id: str,
    ) -> list[str]:
        """获取用户绑定的所有 UID

        Args:
            user_id: QQ 用户 ID
            bot_id: Bot ID

        Returns:
            UID 列表
        """
        data = await cls.get_data_by_user_id(user_id, bot_id)
        if data and data.uid:
            return data.uid.split('_')
        return []

    @classmethod
    @with_session
    async def get_group_ids(
        cls,
        session: AsyncSession,
        user_id: str,
        bot_id: str,
    ) -> list[str]:
        """读取当前用户的绑定群 ID 列表"""
        stmt = select(cls.group_id).where(
            and_(
                cls.user_id == user_id,
                cls.bot_id == bot_id,
            )
        )
        result = await session.execute(stmt)
        return [gid for gid in result.scalars().all() if gid]

    @classmethod
    @with_session
    async def delete_bind(
        cls,
        session: AsyncSession,
        user_id: str,
        bot_id: str,
    ) -> bool:
        """删除绑定记录（用于解绑）"""
        sql = select(cls).where(
            and_(cls.user_id == user_id, cls.bot_id == bot_id)
        )
        result = await session.execute(sql)
        data = result.scalars().first()
        if not data:
            return False
        await session.delete(data)
        return True


class EndUser(User, table=True):
    """终末地用户详细信息表"""

    __tablename__ = "EndUser"
    __table_args__ = (
        Index('idx_uid_user_bot', 'uid', 'user_id', 'bot_id'),
        Index('idx_last_used', 'last_used_time'),
        Index('idx_cookie_status', 'cookie_status'),
        {"extend_existing": True}
    )

    # 游戏 UID
    uid: str = Field(default="", title="游戏 UID")
    cookie: str = Field(default="", title="森空岛 Cred")

    # 账号信息
    nickname: str = Field(default="", title="游戏昵称")

    # 认证信息
    token: Optional[str] = Field(default=None, title="OAuth Token")
    platform: str = Field(default="3", title="平台 ID")

    # 记录编号
    record_id: Optional[str] = Field(default=None, title="账号 ID")
    server_id: str = Field(default="1", title="服务器 ID")
    skland_user_id: str = Field(default="", title="森空岛 用户ID")

    # Cookie 状态
    cookie_status: str = Field(default="", title="Cookie 状态")

    # 配置
    bbs_sign_switch: str = Field(default="off", title="签到开关")
    stamina_bg_value: str = Field(default="", title="体力背景")

    # 时间戳
    created_time: Optional[int] = Field(default=None, title="创建时间（秒）")
    last_used_time: Optional[int] = Field(default=None, title="最后使用时间（秒）")
    last_cred_request_time: Optional[int] = Field(default=None, title="上次请求 cred 时间（秒）")

    @classmethod
    @with_session
    async def select_data_by_cred(
        cls,
        session: AsyncSession,
        cred: str,
    ) -> Optional['EndUser']:
        """通过 cred 查询用户（用于 token 缓存）"""
        sql = select(cls).where(cls.cookie == cred)
        result = await session.execute(sql)
        data = result.scalars().all()
        return data[0] if data else None

    @classmethod
    @with_session
    async def select_end_user(
        cls,
        session: AsyncSession,
        uid: str,
        user_id: str,
        bot_id: str,
    ) -> Optional['EndUser']:
        """查询用户信息"""
        filters = [
            cls.user_id == user_id,
            cls.uid == uid,
            cls.bot_id == bot_id,
        ]
        sql = select(cls).where(*filters)
        result = await session.execute(sql)
        data = result.scalars().all()
        return data[0] if data else None

    @classmethod
    @with_session
    async def update_last_used_time(
        cls,
        session: AsyncSession,
        uid: str,
        user_id: str,
        bot_id: str,
    ):
        """更新最后使用时间"""
        current_time = int(time.time())

        filters = [
            cls.user_id == user_id,
            cls.uid == uid,
            cls.bot_id == bot_id,
        ]
        result = await session.execute(select(cls).where(*filters))
        user = result.scalars().first()

        if user and user.cookie:
            all_result = await session.execute(
                select(cls).where(
                    and_(
                        col(cls.user_id) == user_id,
                        col(cls.cookie) == user.cookie,
                    )
                )
            )
            all_users = all_result.scalars().all()
            for u in all_users:
                u.last_used_time = current_time
                if u.created_time is None:
                    u.created_time = current_time
            return True
        return False

    @classmethod
    @with_session
    async def mark_invalid(
        cls,
        session: AsyncSession,
        uid: str,
        user_id: str,
        bot_id: str,
    ):
        """标记 Cookie 为无效"""
        filters = [
            cls.user_id == user_id,
            cls.uid == uid,
            cls.bot_id == bot_id,
        ]
        result = await session.execute(select(cls).where(*filters))
        user = result.scalars().first()
        if user:
            await session.execute(
                update(cls)
                .where(
                    and_(
                        col(cls.user_id) == user_id,
                        col(cls.cookie) == user.cookie,
                    )
                )
                .values(cookie_status="无效")
            )

    @classmethod
    @with_session
    async def delete_end_user(
        cls,
        session: AsyncSession,
        uid: str,
        user_id: str,
        bot_id: str,
    ) -> bool:
        """删除指定用户记录"""
        sql = select(cls).where(
            and_(cls.uid == uid, cls.user_id == user_id, cls.bot_id == bot_id)
        )
        result = await session.execute(sql)
        data = result.scalars().first()
        if not data:
            return False
        await session.delete(data)
        return True


    @classmethod
    async def get_all_valid_users(cls) -> list['EndUser']:
        """获取所有有效用户"""
        # 查询条件：
        # - cookie 非空
        # - cookie_status != "无效"
        # - last_used_time 在最近 N 天内（活跃用户）
        active_days = 30
        try:
            from ...end_config import EndConfig
            config_val = EndConfig.get_config("ActiveDays").data
            if isinstance(config_val, int):
                active_days = config_val
            else:
                active_days = int(config_val)
        except Exception:
            active_days = 30

        if active_days < 1:
            active_days = 1

        threshold = int(time.time()) - (active_days * 86400)

        users = await cls.get_all_data()
        valid_users = [
            u for u in users
            if u.cookie
            and u.cookie_status != "无效"
            and (u.last_used_time is None or u.last_used_time >= threshold)
        ]
        return valid_users

    @classmethod
    async def get_active_user_count(
        cls,
        active_days: int = 30,
    ) -> int:
        """获取活跃用户数量"""
        threshold = int(time.time()) - (active_days * 86400)

        users = await cls.get_all_data()
        active_users = [
            u for u in users
            if u.cookie
            and u.cookie_status != "无效"
            and u.last_used_time
            and u.last_used_time >= threshold
        ]
        return len(active_users)



class EndSubscribe(BaseModel, table=True):
    """Bot-群组绑定表"""

    __tablename__ = "EndSubscribe"
    __table_args__ = {"extend_existing": True}

    group_id: str = Field(default="", title="群组 ID", unique=True)
    bot_self_id: str = Field(default="", title="Bot Self ID")
    updated_at: Optional[int] = Field(default=None, title="最后更新时间（秒）")

    @classmethod
    @with_session
    async def check_and_update_bot(
        cls,
        session: AsyncSession,
        group_id: str,
        bot_self_id: str,
    ) -> bool:
        """检查并更新群组的 bot_self_id

        只要 Subscribe 表中该群的 bot_self_id 与当前不一致就更新
        """
        from gsuid_core.logger import logger

        current_time = int(time.time())

        # 更新 Subscribe 表：该群所有 bot_self_id 不一致的订阅记录
        update_sql = (
            update(Subscribe)
            .where(
                and_(
                    col(Subscribe.group_id) == group_id,
                    col(Subscribe.bot_self_id) != bot_self_id,
                )
            )
            .values(bot_self_id=bot_self_id)
        )
        update_result = await session.execute(update_sql)
        changed = update_result.rowcount > 0

        if changed:
            logger.info(
                f"[EndUID订阅] 群 {group_id} 更新 {update_result.rowcount} 条订阅的bot_self_id -> {bot_self_id}"
            )

        # 更新 EndSubscribe 记录
        sql = select(cls).where(cls.group_id == group_id)
        result = await session.execute(sql)
        existing = result.scalars().first()

        if existing:
            if existing.bot_self_id != bot_self_id:
                existing.bot_self_id = bot_self_id
            existing.updated_at = current_time
            session.add(existing)
        else:
            new_record = cls(
                bot_id="onebot",
                user_id="",
                group_id=group_id,
                bot_self_id=bot_self_id,
                updated_at=current_time,
            )
            session.add(new_record)

        return changed

    @classmethod
    @with_session
    async def get_group_bot(
        cls,
        session: AsyncSession,
        group_id: str,
    ) -> Optional[str]:
        """获取群组当前的bot_self_id"""
        sql = select(cls).where(cls.group_id == group_id)
        result = await session.execute(sql)
        record = result.scalars().first()
        return record.bot_self_id if record else None


class EndUserActivity(BaseBotIDModel, table=True):
    """用户活跃度记录表（由 Hook 自动管理）"""

    __tablename__ = "EndUserActivity"
    __table_args__ = {"extend_existing": True}

    user_id: str = Field(default="", title="QQ 用户 ID")
    bot_self_id: str = Field(default="", title="Bot Self ID")
    last_active_time: Optional[int] = Field(default=None, title="最后活跃时间（秒）")

    @classmethod
    @with_session
    async def update_user_activity(
        cls: Type["EndUserActivity"],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        bot_self_id: str,
    ) -> bool:
        """更新用户活跃度（支持数据迁移）"""
        current_time = int(time.time())

        sql = select(cls).where(
            and_(
                cls.user_id == user_id,
                cls.bot_id == bot_id,
                cls.bot_self_id == bot_self_id,
            )
        )
        result = await session.execute(sql)
        existing = result.scalars().first()

        if existing:
            existing.last_active_time = current_time
            session.add(existing)
            return True

        legacy_sql = select(cls).where(
            and_(
                cls.user_id == user_id,
                cls.bot_id == bot_self_id,
                or_(cls.bot_self_id == "", cls.bot_self_id.is_(None)),
            )
        )
        legacy_result = await session.execute(legacy_sql)
        legacy = legacy_result.scalars().first()
        if legacy:
            legacy.bot_id = bot_id
            legacy.bot_self_id = bot_self_id
            legacy.last_active_time = current_time
            session.add(legacy)
            return True

        new_record = cls(
            user_id=user_id,
            bot_id=bot_id,
            bot_self_id=bot_self_id,
            last_active_time=current_time,
        )
        session.add(new_record)
        return True


class EndSignRecord(BaseModel, table=True):
    """每日签到记录表"""

    __tablename__ = "EndSignRecord"
    __table_args__ = {"extend_existing": True}

    uid: str = Field(default="", title="游戏 UID")
    sign_status: int = Field(default=0, title="签到状态 (1=已签到)")
    date: str = Field(default="", title="签到日期")

    @classmethod
    @with_session
    async def get_sign_record(
        cls,
        session: AsyncSession,
        uid: str,
        date: Optional[str] = None,
    ) -> Optional["EndSignRecord"]:
        """查询指定 UID 当天的签到记录"""
        date = date or datetime.now().strftime("%Y-%m-%d")
        sql = select(cls).where(and_(cls.uid == uid, cls.date == date))
        result = await session.execute(sql)
        return result.scalars().first()

    @classmethod
    @with_session
    async def mark_signed(
        cls,
        session: AsyncSession,
        uid: str,
        date: Optional[str] = None,
    ):
        """标记用户今日已签到"""
        date = date or datetime.now().strftime("%Y-%m-%d")
        sql = select(cls).where(and_(cls.uid == uid, cls.date == date))
        result = await session.execute(sql)
        existing = result.scalars().first()

        if existing:
            existing.sign_status = 1
            session.add(existing)
        else:
            record = cls(
                bot_id="",
                user_id="",
                uid=uid,
                sign_status=1,
                date=date,
            )
            session.add(record)

    @classmethod
    @with_session
    async def clear_sign_records(
        cls,
        session: AsyncSession,
        before_date: str,
    ):
        """清除指定日期之前的签到记录"""
        sql = delete(cls).where(cls.date <= before_date)
        await session.execute(sql)


@site.register_admin
class EndUserAdmin(GsAdminModel):
    pk_name = "id"
    page_schema = PageSchema(
        label="终末地用户管理",
        icon="fa fa-users",
    )
    model = EndUser


@site.register_admin
class EndBindAdmin(GsAdminModel):
    pk_name = "id"
    page_schema = PageSchema(
        label="终末地绑定管理",
        icon="fa fa-users",
    )
    model = EndBind


@site.register_admin
class EndSubscribeAdmin(GsAdminModel):
    pk_name = "group_id"
    page_schema = PageSchema(
        label="终末地发送-群组绑定",
        icon="fa fa-link",
    )
    model = EndSubscribe


@site.register_admin
class EndUserActivityAdmin(GsAdminModel):
    pk_name = "id"
    page_schema = PageSchema(
        label="终末地用户活跃度",
        icon="fa fa-clock-o",
    )
    model = EndUserActivity
