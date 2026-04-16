from docx import Document
from csrcqsf.settings import minio_bucket
from csrcqsf.data.minio import minio_instance
import pandas as pd
from csrcqsf.data.pg import SessionLocal
from csrcqsf.models.files import Files, FileTables
from bfrcommon.snowflake import get_id
from anyio.to_thread import run_sync
from globals_vars import logger
import io
from csrcqsf.logger import CodeTimer
from csrcqsf.settings import temp_dir, minio_bucket
import os
from io import StringIO

# 尝试导入 grpc_client，如果失败则设为 None
try:
    from csrcqsf.data.basis_api import grpc_client
except ModuleNotFoundError as e:
    logger.warning(f"无法导入 grpc_client: {e}. 文档解析功能可能受限")
    grpc_client = None

class DocBiz:

    @classmethod
    def get_paragraph_before_table(cls, doc, table_index=0, start_element_index=0):
        """
        获取指定表格前的一个段落文本。

        Args:
            doc: Document对象。
            table_index: 所需表格的索引（默认为0，即第一个表格）。

        Returns:
            str: 段落文本。如果未找到段落或表格索引无效，则返回空字符串。
        """
        # 检查表格索引是否有效
        if table_index < 0 or table_index >= len(doc.tables):
            print(f"表格索引 {table_index} 无效。文档中共有 {len(doc.tables)} 个表格。")
            return "", 0

        target_table = doc.tables[table_index]
        previous_paragraph_text = ""

        # 遍历文档中的所有元素（按顺序）
        loop_count = 0
        for index, element in enumerate(doc.element.body[start_element_index:], start_element_index):
            loop_count = loop_count + 1
            if element == target_table._element:
                # 找到目标表格，返回之前记录的段落文本
                logger.info(f'为了找到表名遍历次数为{loop_count}，索引index{index}')
                return previous_paragraph_text, index
            elif element.tag.endswith('p'):  # 如果当前元素是段落（p）
                # 获取这个段落的文本内容
                paragraph = None
                for p in doc.paragraphs:
                    if p._element == element:
                        paragraph = p
                        break
                if paragraph:
                    # 记录当前段落的文本（会不断更新，直到遇到目标表格）
                    previous_paragraph_text = paragraph.text.strip()
        # 如果遍历结束仍未找到表格（理论上不应发生，因索引已检查）
        return "", 0

    @classmethod
    def rename_duplicate_columns(cls, df: pd.DataFrame):
        """
        为DataFrame的重复列名添加后缀以使其唯一
        """
        cols = pd.Series(df.columns)
        for dup in cols[cols.duplicated()].unique():
            # 为重复的列名添加后缀 _1, _2, ...
            indices = cols[cols == dup].index
            suffixes = [f'_{i+1}' if i >
                        0 else '' for i in range(len(indices))]
            new_names = [dup + suffix for suffix in suffixes]
            cols.iloc[indices] = new_names
        df.columns = cols
        return df

    @classmethod
    async def create_file(cls, file_name: str, file_url: str):
        json_data_dict: dict[str, str] = {}
        file_name_arr = file_url.split("/")
        if len(file_name_arr) < 2:
            raise Exception(f'文件名格式不正确')
        df = None
        aim_file_name = file_name_arr[1]

        try:
            response = await run_sync(minio_instance.client.get_object,
                                      minio_bucket, aim_file_name)
            # Read data from response.
            if response.status != 200:
                raise Exception(f'oss请求出错')
            now_element_index = 0
            if response.data:
                try:
                    docs = Document(io.BytesIO(response.data))
                    for index, table in enumerate(docs.tables):
                        table_data = []
                        logger.info(
                            f"开始处理第{index+1}个表，总共有{len(docs.tables)},进度{index/len(docs.tables)*100}%")
                        for row in table.rows:
                            row_data: list[str] = [cell.text.strip().replace(" ", '')
                                                   for cell in row.cells]  # 去除文本前后的空白字符
                            table_data.append(row_data)
                        if len(table_data) > 0:
                            header = ''
                            for cell in table_data[0]:
                                header = header + '' + cell
                            if '图号' in header and '物料编码' in header:
                                df = pd.DataFrame(
                                    table_data[1:], columns=table_data[0])
                                duplicate_columns = df.columns[df.columns.duplicated(
                                )]
                                if len(duplicate_columns) > 0:
                                    print(header)

                                    df = cls.rename_duplicate_columns(df)
                                with CodeTimer("找到表格名"):
                                    table_name, now_element_index = await run_sync(cls.get_paragraph_before_table,
                                                                                   docs, index, now_element_index)
                                json_data_dict[table_name] = df.to_json(
                                    force_ascii=False, orient='records', indent=4
                                )

                except Exception as e:
                    logger.error(f'文档解析出错{e}')
                    raise Exception(f'必须为docx格式的文档')

        finally:
            if response:
                response.close()
                response.release_conn()
        if len(json_data_dict) > 0:
            tables = []
            async with SessionLocal() as session:
                data = Files(
                    file_name=file_name,
                    file_url=file_url,
                    table_num=len(json_data_dict),
                    id=get_id()
                )
                session.add(data)
                for table_name, json_data in json_data_dict.items():
                    table = FileTables(
                        file_id=data.id,
                        table_name=table_name,
                        table_data=json_data
                    )
                    tables.append(table)
                if len(tables) > 0:
                    session.add_all(tables)
                await session.commit()

    @classmethod
    async def list_files(cls, page: int, per_page: int, query: str = None):
        async with SessionLocal() as session:
            files = await Files.list_files(session, query, page, per_page)
            return files

    @classmethod
    async def list_tables(cls, file_id: int, page: int, per_page: int, query: str):
        async with SessionLocal() as session:
            tables = await FileTables.list_tables(session, file_id, query, page, per_page)
            return tables

    @classmethod
    async def write_to_excel(cls, file_id: int, user_id: int):

        async with SessionLocal() as session:
            file = await Files.get_file(session, file_id)
            if file is None:
                raise Exception(f'源文件不存在')

        tables = await cls.list_tables(file_id, -1, 0, None)

        obj_name = f"{get_id()}.xlsx"
        # excel_full_path = os.path.join(temp_dir, excel_path)
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
            for table in tables.data:
                # 设置index=False避免写入行索引
                df = pd.read_json(StringIO(table.table_data))
                df.to_excel(writer, sheet_name=table.table_name, index=False)
                
        excel_buffer.seek(0)

        minio_instance.client.put_object(
            minio_bucket,
            obj_name,
            excel_buffer,
            length=excel_buffer.getbuffer().nbytes,  # 设置对象大小
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

        grpc_client.send_file_task(
            obj_name, excel_buffer.getbuffer().nbytes, user_id, file.file_name)
