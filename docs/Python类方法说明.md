# Python 类方法（classmethod）说明

## 🔍 cls 参数是什么？

`cls` 是 Python 中**类方法（classmethod）**的第一个参数，代表**类本身**。

---

## 📚 三种方法类型对比

### 1. 实例方法（Instance Method）
```python
class MyClass:
    def instance_method(self, param):
        """
        实例方法
        - 第一个参数：self（实例本身）
        - 调用方式：obj.instance_method(param)
        - 可以访问：实例属性、类属性
        """
        print(f"实例: {self}")
        print(f"参数: {param}")

# 使用
obj = MyClass()
obj.instance_method("hello")  # 需要先创建实例
```

### 2. 类方法（Class Method）⭐
```python
class MyClass:
    @classmethod
    def class_method(cls, param):
        """
        类方法
        - 第一个参数：cls（类本身）
        - 调用方式：MyClass.class_method(param)
        - 可以访问：类属性、类方法
        - 不能访问：实例属性
        """
        print(f"类: {cls}")
        print(f"参数: {param}")

# 使用
MyClass.class_method("hello")  # 不需要创建实例
```

### 3. 静态方法（Static Method）
```python
class MyClass:
    @staticmethod
    def static_method(param):
        """
        静态方法
        - 没有 self 或 cls 参数
        - 调用方式：MyClass.static_method(param)
        - 不能访问：实例属性、类属性
        - 就像普通函数，只是放在类里
        """
        print(f"参数: {param}")

# 使用
MyClass.static_method("hello")  # 不需要创建实例
```

---

## 🎯 项目中的使用示例

### 示例1: RailwayPartsManager 中的类方法

```python
class RailwayPartsManager:
    """配件管理核心业务类"""
    
    _milvus_manager = MilvusManager()  # 类属性
    
    @classmethod
    async def rebuild_pic_index(cls):
        """
        类方法示例
        
        cls 参数：
        - cls = RailwayPartsManager（类本身）
        - 可以访问类属性：cls._milvus_manager
        - 可以调用其他类方法：cls.other_method()
        """
        async with SessionLocal() as session:
            await SgoItemImages.make_image_unindexed(session=session)
            images = SgoItemImages.get_all_image(session=session)
            # 使用类属性
            await cls._milvus_manager.rebuild_collection([image async for image in images])
            await SgoItemImages.make_image_indexed(session=session)
            await session.commit()
    
    @classmethod
    async def create_item(cls, item_name: str, item_code: str, ...):
        """
        另一个类方法
        
        cls 参数的作用：
        1. 代表 RailwayPartsManager 类
        2. 可以调用其他类方法：await cls.other_method()
        3. 可以访问类属性：cls._milvus_manager
        """
        item = Items(
            item_name=item_name,
            item_code=item_code,
            id=get_id()
        )
        async with SessionLocal() as session:
            await Items.create_item(session=session, item=item)
            await session.commit()

# 调用方式（不需要创建实例）
await RailwayPartsManager.rebuild_pic_index()
await RailwayPartsManager.create_item("螺栓", "BOLT-001")
```

### 示例2: 数据模型中的类方法

```python
class SgoItemImages(Base):
    """配件图片信息表"""
    __tablename__ = 'sgo_item_image_info'
    
    item_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    image_url: Mapped[str] = mapped_column(String(200), nullable=False)
    is_indexed: Mapped[int] = mapped_column(INT, default=2)
    
    @classmethod
    async def get_all_image(cls, session: AsyncSession):
        """
        类方法：获取所有图片
        
        cls 参数：
        - cls = SgoItemImages（类本身）
        - 用于构建查询：select(cls)
        - 相当于：select(SgoItemImages)
        """
        stmt = select(cls)  # 使用 cls 构建查询
        datas = await session.scalars(stmt)
        for d in datas:
            yield d
    
    @classmethod
    async def make_image_unindexed(cls, session: AsyncSession):
        """
        类方法：标记所有图片为未索引
        
        cls 参数：
        - 用于构建更新语句：update(cls)
        - 相当于：update(SgoItemImages)
        """
        stmt = update(cls).values(is_indexed=0)  # 使用 cls 构建更新
        await session.execute(stmt)
        await session.flush()

# 调用方式
async with SessionLocal() as session:
    # 不需要创建 SgoItemImages 实例
    await SgoItemImages.make_image_unindexed(session)
    images = SgoItemImages.get_all_image(session)
```

---

## 🤔 为什么使用类方法？

### 1. 不需要创建实例
```python
# ❌ 如果是实例方法
manager = RailwayPartsManager()  # 需要先创建实例
await manager.rebuild_pic_index()

# ✅ 使用类方法
await RailwayPartsManager.rebuild_pic_index()  # 直接调用
```

### 2. 工厂模式
```python
class Items(Base):
    @classmethod
    def create_from_dict(cls, data: dict):
        """
        工厂方法：从字典创建实例
        
        cls 参数用于创建类的实例
        """
        return cls(
            item_name=data['name'],
            item_code=data['code'],
            id=get_id()
        )

# 使用
item = Items.create_from_dict({"name": "螺栓", "code": "BOLT-001"})
```

### 3. 数据库查询（ORM模式）
```python
class Items(Base):
    @classmethod
    async def get_by_id(cls, session: AsyncSession, item_id: int):
        """
        查询方法：通过ID获取配件
        
        cls 参数用于构建查询
        """
        stmt = select(cls).where(cls.id == item_id)
        result = await session.scalar(stmt)
        return result

# 使用
item = await Items.get_by_id(session, 123456)
```

---

## ⚠️ 项目中发现的问题

### 问题：缺少 @classmethod 装饰器

```python
# ❌ 错误：缺少装饰器
class RailwayPartsManager:
    async def list_search_history(cls, page: int = 1, per_page: int = 20):
        # cls 参数存在，但没有 @classmethod 装饰器
        # 这会导致调用时出错
        pass

# ✅ 正确：添加装饰器
class RailwayPartsManager:
    @classmethod
    async def list_search_history(cls, page: int = 1, per_page: int = 20):
        """
        类方法：列出检索历史
        
        cls 参数：RailwayPartsManager 类本身
        """
        async with SessionLocal() as session:
            histories = await SearchHistory.list_search_history(session, page, per_page)
            # ...
```

**修复建议**：
在 `csrcqsf/biz/railwayparts/parts.py` 的 `list_search_history` 方法前添加 `@classmethod` 装饰器。

---

## 📊 参数对比表

| 方法类型 | 第一个参数 | 参数含义 | 装饰器 | 调用方式 |
|---------|-----------|---------|--------|---------|
| 实例方法 | `self` | 实例本身 | 无 | `obj.method()` |
| 类方法 | `cls` | 类本身 | `@classmethod` | `Class.method()` |
| 静态方法 | 无 | - | `@staticmethod` | `Class.method()` |

---

## 💡 命名约定

### self vs cls
```python
class MyClass:
    # 实例方法：第一个参数叫 self（约定俗成）
    def instance_method(self):
        pass
    
    # 类方法：第一个参数叫 cls（约定俗成）
    @classmethod
    def class_method(cls):
        pass
```

**注意**：
- `self` 和 `cls` 只是命名约定，不是关键字
- 可以用其他名字，但强烈建议遵循约定
- `self` 代表 "self"（自己，实例）
- `cls` 代表 "class"（类）

---

## 🔧 实际应用场景

### 场景1: 业务逻辑类（无需实例化）
```python
class RailwayPartsManager:
    """
    业务逻辑类
    
    特点：
    - 所有方法都是类方法
    - 不需要创建实例
    - 直接通过类名调用
    """
    
    @classmethod
    async def create_item(cls, ...):
        pass
    
    @classmethod
    async def delete_item(cls, ...):
        pass
    
    @classmethod
    async def rebuild_pic_index(cls):
        pass

# 使用：直接调用，不需要实例化
await RailwayPartsManager.create_item(...)
await RailwayPartsManager.rebuild_pic_index()
```

### 场景2: ORM 模型类（查询方法）
```python
class Items(Base):
    """
    数据模型类
    
    特点：
    - 查询方法使用类方法
    - 实例代表一条数据库记录
    """
    
    # 类方法：查询数据
    @classmethod
    async def get_by_id(cls, session, item_id):
        stmt = select(cls).where(cls.id == item_id)
        return await session.scalar(stmt)
    
    # 实例方法：操作单条记录
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.item_name
        }

# 使用
item = await Items.get_by_id(session, 123)  # 类方法
data = item.to_dict()  # 实例方法
```

---

## 📝 总结

### cls 参数的作用
1. **代表类本身**：`cls = ClassName`
2. **访问类属性**：`cls.class_attribute`
3. **调用类方法**：`cls.other_class_method()`
4. **构建查询**：`select(cls)`, `update(cls)`
5. **创建实例**：`return cls(...)`

### 何时使用类方法
- ✅ 业务逻辑类（不需要实例状态）
- ✅ 工厂方法（创建实例）
- ✅ ORM 查询方法
- ✅ 工具方法（与类相关但不需要实例）

### 何时使用实例方法
- ✅ 需要访问实例属性
- ✅ 操作单个对象的状态
- ✅ 实例相关的业务逻辑

---

**关键点**：在项目中，业务逻辑类（如 `RailwayPartsManager`）的方法都应该是类方法，因为不需要创建实例，直接通过类名调用即可。
