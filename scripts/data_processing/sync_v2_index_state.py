from anyio import run

from csrcqsf.biz.railwayparts.parts import RailwayPartsManager


async def main():
    result = await RailwayPartsManager.sync_all_v2_index_state()
    print(result)


if __name__ == "__main__":
    run(main)
