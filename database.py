from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, update as sqlalchemy_update
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.future import select
from datetime import datetime
import logging
import asyncio

logger = logging.getLogger(__name__)

Base = declarative_base()

class Driver(Base):
    __tablename__ = 'drivers'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True)
    name = Column(String)
    car_model = Column(String)
    car_number = Column(String)
    status = Column(String)  # 'active', 'inactive', 'busy'
    registration_date = Column(DateTime, default=datetime.utcnow)

class Queue(Base):
    __tablename__ = 'queue'
    
    id = Column(Integer, primary_key=True)
    driver_id = Column(Integer, ForeignKey('drivers.id'))
    position = Column(Integer)
    join_time = Column(DateTime, default=datetime.utcnow)
    
    driver = relationship("Driver")

class Database:
    def __init__(self):
        self.engine = create_async_engine('sqlite+aiosqlite:///taxi_bot.db', echo=True)
        self.async_session = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def init_db(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def add_driver(self, driver_data):
        async with self.async_session() as session:
            try:
                driver = Driver(
                    telegram_id=driver_data['telegram_id'],
                    name=driver_data['name'],
                    car_model=driver_data['car_model'],
                    car_number=driver_data['car_number'],
                    status=driver_data['status']
                )
                session.add(driver)
                await session.commit()
                logger.info(f"Driver added: {driver_data['telegram_id']}")
            except Exception as e:
                logger.error(f"Error adding driver: {e}")
                await session.rollback()
                raise

    async def get_driver(self, telegram_id):
        async with self.async_session() as session:
            try:
                result = await session.execute(
                    select(Driver).where(Driver.telegram_id == telegram_id)
                )
                return result.scalar_one_or_none()
            except Exception as e:
                logger.error(f"Error getting driver: {e}")
                return None

    async def is_driver_registered(self, telegram_id):
        try:
            driver = await self.get_driver(telegram_id)
            return driver is not None
        except Exception as e:
            logger.error(f"Error checking driver registration: {e}")
            return False

    async def add_to_queue(self, telegram_id):
        async with self.async_session() as session:
            try:
                # Get driver
                driver = await self.get_driver(telegram_id)
                if not driver:
                    logger.error(f"Driver not found: {telegram_id}")
                    return False

                # Check if already in queue
                result = await session.execute(
                    select(Queue).where(Queue.driver_id == driver.id)
                )
                if result.scalar_one_or_none():
                    logger.warning(f"Driver already in queue: {telegram_id}")
                    return False

                # Get last position in queue
                result = await session.execute(
                    select(Queue).order_by(Queue.position.desc())
                )
                last_queue = result.scalar_one_or_none()
                new_position = 1 if not last_queue else last_queue.position + 1

                # Add to queue
                queue_entry = Queue(driver_id=driver.id, position=new_position)
                session.add(queue_entry)
                
                # Update driver status
                driver.status = 'active'
                
                await session.commit()
                logger.info(f"Driver added to queue: {telegram_id}, position: {new_position}")
                return True
            except Exception as e:
                logger.error(f"Error adding to queue: {e}")
                await session.rollback()
                return False

    async def remove_from_queue(self, telegram_id):
        async with self.async_session() as session:
            try:
                # Get driver
                driver = await self.get_driver(telegram_id)
                if not driver:
                    logger.error(f"Driver not found: {telegram_id}")
                    return False

                # Remove from queue
                result = await session.execute(
                    select(Queue).where(Queue.driver_id == driver.id)
                )
                queue_entry = result.scalar_one_or_none()
                
                if queue_entry:
                    await session.delete(queue_entry)
                    driver.status = 'inactive'
                    await session.commit()
                    
                    # Reorder queue positions
                    await self.reorder_queue()
                    logger.info(f"Driver removed from queue: {telegram_id}")
                    return True
                logger.warning(f"Driver not in queue: {telegram_id}")
                return False
            except Exception as e:
                logger.error(f"Error removing from queue: {e}")
                await session.rollback()
                return False

    async def is_driver_in_queue(self, telegram_id):
        async with self.async_session() as session:
            try:
                driver = await self.get_driver(telegram_id)
                if not driver:
                    return False
                
                # Check both queue table and driver status
                result = await session.execute(
                    select(Queue).join(Driver).where(Driver.telegram_id == telegram_id)
                )
                in_queue = result.scalar_one_or_none() is not None
                
                # If statuses don't match, fix it
                if in_queue != (driver.status == 'active'):
                    driver.status = 'active' if in_queue else 'inactive'
                    await session.commit()
                
                return in_queue
            except Exception as e:
                logger.error(f"Error checking queue status: {e}")
                return False

    async def get_queue_position(self, telegram_id):
        async with self.async_session() as session:
            try:
                driver = await self.get_driver(telegram_id)
                if not driver:
                    return None
                
                result = await session.execute(
                    select(Queue).where(Queue.driver_id == driver.id)
                )
                queue_entry = result.scalar_one_or_none()
                return queue_entry.position if queue_entry else None
            except Exception as e:
                logger.error(f"Error getting queue position: {e}")
                return None

    async def reorder_queue(self):
        async with self.async_session() as session:
            try:
                result = await session.execute(
                    select(Queue).order_by(Queue.join_time)
                )
                queue_entries = result.scalars().all()
                
                for i, entry in enumerate(queue_entries, 1):
                    entry.position = i
                
                await session.commit()
                logger.info("Queue reordered successfully")
            except Exception as e:
                logger.error(f"Error reordering queue: {e}")
                await session.rollback()

    async def get_first_in_queue(self):
        async with self.async_session() as session:
            try:
                result = await session.execute(
                    select(Queue).order_by(Queue.position).limit(1)
                )
                queue_entry = result.scalar_one_or_none()
                if queue_entry:
                    driver_result = await session.execute(
                        select(Driver).where(Driver.id == queue_entry.driver_id)
                    )
                    return driver_result.scalar_one_or_none()
                return None
            except Exception as e:
                logger.error(f"Error getting first in queue: {e}")
                return None 