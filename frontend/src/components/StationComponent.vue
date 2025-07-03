
<template>
    <g>
      <!-- 绘制方形，加上边框 -->
      <rect :x="station.x" :y="station.y" width="50" height="50" fill="lightgrey" stroke="black" stroke-width="2"/>
      
      <!-- 绘制四个状态指示灯，这里不改变 -->
      <circle :cx="station.x + 12.5" :cy="station.y + 12.5" r="5" fill="red" />
      <circle :cx="station.x + 37.5" :cy="station.y + 12.5" r="5" fill="green" />
      <circle :cx="station.x + 12.5" :cy="station.y + 37.5" r="5" fill="blue" />
      <circle :cx="station.x + 37.5" :cy="station.y + 37.5" r="5" fill="yellow" />
      
      <!-- 绘制车站名称，位置根据需要进行调整 -->
      <text :x="station.x" :y="station.y + 65" fill="black">{{ station.name }}</text>
    </g>
  </template>
  
  <script>
  export default {
    props: ['station'],
  };
  </script>
  