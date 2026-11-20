"""Pro 主机运行入口: 重定向 pdf_path 到本地 staging 后调用 v3 对比逻辑"""
import json, os, sys

PRO_STAGING = '/source/annual-semi/pdf-staging'

def main():
    with open('data/pdf_validation_results.json', 'r', encoding='utf-8') as f:
        results = json.load(f)

    n_fixed = 0
    for r in results:
        p = r.get('pdf_path')
        if p:
            r['pdf_path'] = os.path.join(PRO_STAGING, os.path.basename(p.replace('\\', '/')))
            if os.path.exists(r['pdf_path']):
                n_fixed += 1

    with open('data/pdf_validation_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f'pdf_path 重定向: {n_fixed}/{sum(1 for r in results if r.get("pdf_path"))} 命中本地 staging')
    missing = [os.path.basename(r['pdf_path']) for r in results
               if r.get('pdf_path') and not os.path.exists(r['pdf_path'])]
    if missing:
        print(f'缺失: {missing}')

    import pdf_md_compare_v3
    pdf_md_compare_v3.main()

if __name__ == '__main__':
    main()
