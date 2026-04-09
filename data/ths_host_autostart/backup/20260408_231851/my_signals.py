#!/usr/bin/env python
#  -*- coding: utf-8 -*-

'''
@brief 信号实现
'''

from ths_api import *


# 涨幅大于3%，并且上证指数涨幅超过3%
#run('600000, 000001', "quote[code]['zf'] > 0.01 and quote2['1A0001']['zf'] > 0.03", "xd.cmd('buy {0} {1} 100'.format(code, quote[code]['price']))")
#run('macd金叉,缩量', "quote[code]['zf'] > 0.01 and quote2['1A0001']['zf'] > 0.03", "xd.cmd('buy {0} {1} 100'.format(code, quote[code]['price']))")
# 炸板预卖：持仓股票小于10万元就清仓
#run('position', "f_dkztb(quote, code, 1000000)", "xd.cmd('sell {0} {1} -cw 1/1'.format(code, quote[code]['price']))")
#run('600000, 000001', "quote[code]['price'] < api.MA(kline,code,5).iloc[-1]['ma']", "xd.cmd('buy {0} {1} 100 -notip'.format(code, quote[code]['price']))")
#run('601020', "quote[code]['price'] > kline[code][-2]['low']","xd.cmd('buy {0} {1} 100'.format(code,str(quote[code]['dt_p'])))")

#计算当日的60日均线值需要最近的60条日线，信号中kline默认取30条日线数据，因此数据不够，需要设置lenth参数
#run('自选股', "quote[code]['price'] > api.MA( kline, code, 60, m=0).iloc[-1,0]",  "xd.cmd('buy {0} {1} 100'.format(code, quote[code]['price']))", lenth=60)

# 定时信号样例
#run('600000', "f_sj(140000)", "xd.cmd('buy {0} zxjg 100'.format(code))")
#run('macd底背离前10', "xd.g_money['kyje']/xd.g_money['zzc']>0.8", "xd.cmd('buy {0} zxjg 500 -notip'.format(code))")


dict_params = {
    "codelist" : "600000, 000001",
    "condition" : "quote[code]['price'] > ma5[-1]",
    "action" : "xd.cmd('buy {0} {1} 100 -notip'.format(code, quote[code]['price']))"
}

dict_descs = {
    "codelist" : {
        "desc" : "代码列表",
        "type" : "edit"
    },
    "condition" : {
        "desc" : "触发条件",
        "type" : "edit"
    },
    "action" : {
        "desc" : "触发后行为",
        "type" : "edit"
    }
}

# 数据预定义
pre = [
    "quote[code]['b1_fdl'] = float(quote[code]['b1_p']) * float(quote[code]['b1_v'])",
    "ma5 = api.MA(kline, code, 5).iloc[:,0].tolist()"
]

extra = {
    'name' : '测试信号',
    'desc' : '仅仅测试用'
}

id = run(dict_params['codelist'], dict_params['condition'], dict_params['action'], predefine=pre, extra=extra)

