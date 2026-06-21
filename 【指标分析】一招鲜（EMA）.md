# 短线趋势（一招鲜）指标分析

## 指标源码

### （0）参数设置

| 名称 | 最小 | 最大 | 缺省 |
| ---- | ---- | ---- | ---- |
| P1   | 1    | 300  | 6    |
| P2   | 1    | 300  | 12   |
| P3   | 1    | 300  | 55   |
| P4   | 1    | 300  | 66   |



### （1）富期通

```pascal
MA1:EMA(CLOSE,P1);
MA2:EMA(CLOSE,P2);
MA3:EMA(CLOSE,P3);

// 倍量阳
IS_K_POSITIVE := CLOSE > OPEN;
A1 := C>MA(C,60);
A2 := VOL>2*REF(VOL,1);
A3 := C>REF(C,1);

STICKLINE(IS_K_POSITIVE && A1 && A2 && A3, CLOSE, OPEN, COLORYELLOW, 0);
STICKLINE(IS_K_POSITIVE && NOT(A1) && A2 && A3, CLOSE, OPEN, COLORMAGENTA, 0);

// 倍量阴
STICKLINE(NOT(IS_K_POSITIVE) && A2, CLOSE, OPEN, COLORGREEN, 0);

// 短线趋势（一招鲜）
DRAWCOLORLINE(MA1 >= MA2, MA1, RGB(255,72,72), RGB(128,255,0)), LINETHICK3;
DRAWCOLORLINE(MA1 >= MA2, MA2, RGB(255,72,72), RGB(128,255,0)), LINETHICK3;

// 买卖信号
N:=5;N1:=21;
VAR1:=4*SMA((CLOSE-LLV(LOW,N))/(HHV(HIGH,N)-LLV(LOW,N))*100,5,1)-3
*SMA(SMA((CLOSE-LLV(LOW,N))/(HHV(HIGH,N)-LLV(LOW,N))*100,5,1),3.2,1);
VAR1A:=(HHV(HIGH,9)-CLOSE)/(HHV(HIGH,9)-LLV(LOW,9))*100-70;
VAR2A:=SMA(VAR1A,9,1)+100;
VAR3A:=(CLOSE-LLV(LOW,9))/(HHV(HIGH,9)-LLV(LOW,9))*100;
VAR4A:=SMA(VAR3A,3,1);
VAR5A:=SMA(VAR4A,3,1)+100;
VAR6A:=VAR5A-VAR2A;
MM:=IF(VAR6A>N1,VAR6A-N1,0);
AA:= REF(MM,1)<MM;
BB:= REF(MM,1)>MM;

买入信号:=CROSS(MM, REF(MM,1));
卖出信号:=CROSS(REF(MM,1), MM);
//DRAWTEXT(买入信号, LOW, '↑' ), ALIGN1, VALIGN0, FONTSIZE16, COLORRED;
//DRAWTEXT(卖出信号, LOW, '↓' ), ALIGN1, VALIGN0, FONTSIZE16, COLORGREEN;

//当最后一根K线为买入信号时，将背景设置为从左到右，红色到黑色的渐变。
DRAWGBK(买入信号, RGB(145,0,0), COLORBLACK, 0);
DRAWGBK(卖出信号, RGB(0,145,0), COLORBLACK, 0);
```



## 参考

- [William Blau 的 MQL5 指标与交易系统。第一部分：指标](https://www.mql5.com/zh/articles/190)

  > 本文的第一部分 - <William Blau 的 MQL5 指标与交易系统。第一部分：指标>，是对技术指标与摆动指标的描述，详见 William Blau 下述书中内容 [《动量、方向和背离》](https://www.mql5.com/go?link=https://www.amazon.com/Momentum-Direction-Divergence-Indicators-Technical/dp/0471027294)。
  >
  > 本文中所述之技术指标与摆动指标，均作为 MQL5 语言中的源代码呈现，且已附到归档文件 "Blau_Indicators_MQL5_en.zip" 中。
  >
  > 
  >
  > **William Blau 提出的关键分析理念**
  >
  > William Blau 的技术分析由四个阶段构成：
  >
  > 1. 利用价格系列数据（q 柱）计算指标并绘于图表。*指标并不反映价格变动的总体趋势，亦不可确定趋势反转点。*
  > 2. 指标会利用 EMA 方法平滑多次：第一次（周期为 r）、第二次（周期为 s），以及第三次（周期为 u）；一个平滑的指标绘制完毕。*平滑指标相当精确，会重现出最小延迟的价格波动。它允许确定价格变化的趋势和反转点，并会消除价格噪声。*
  > 3. 将平滑指标标准化，再绘制标准化的平滑指标。*标准化允许指标值被解释为市场的超买或超卖状态。*
  > 4. 利用 EMA 方法将标准化的平滑指标平滑一次（周期 ul）；构造一个摆动指标 - 添加指标柱与信号线、市场的超买与超卖水平。*摆动指标允许我们区分市场的超买/超卖状态、反转点以及趋势结束。*