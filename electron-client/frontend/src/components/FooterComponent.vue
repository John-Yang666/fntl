<template>
  <footer>
    <div class="footer-content">
      <h3>武汉贝通科技有限公司</h3>
      <p>地址：1234 街道，城市，国家</p>
      <p>电话：+123-456-7890</p>
      <p>邮箱：123@company.com</p>
    </div>
  </footer>
</template>

<script lang="ts" setup>
</script>

<style scoped>
.footer-content {
  background-color: #333;
  color: white;
  padding: 20px 0;
  text-align: center;
  opacity: 0;
  transform: translateY(20px);
  animation: fadeInUp 1s forwards;
  animation-delay: 1s;
  z-index: 100; /* 提高层级 */
  position: relative; /* 确保 z-index 生效 */
}

/* 定义动画 */
@keyframes fadeInUp {
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>