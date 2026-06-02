from anyio import run

from csrcqsf.modules.railway_parts.services.parts_service import RailwayPartsManager


async def main():
    result = await RailwayPartsManager.sync_all_v2_index_state()
    print(result)


if __name__ == "__main__":
    run(main)
