<template>
  <div class="help-page">
    <el-container>
      <el-header>
        <h1>感谢您的使用！</h1>
      </el-header>
      <el-main>
        <el-card class="box-card">
          <template #header>
            <div class="clearfix">常见问题解答</div>
          </template>
          <el-collapse>
            <el-collapse-item title="告警码含义" name="1">
              <p>
                0 设备网管连接中断<br />
                40 1方向电源板A状态<br />
                41 1方向电源板B状态<br />
                42 2方向电源板A状态<br />
                43 2方向电源板B状态<br />
                44 1方向CPU板A通信状态<br />
                45 1方向CPU板B通信状态<br />
                46 2方向CPU板A通信状态<br />
                47 2方向CPU板B通信状态<br />
                70 提醒：1方向QHJ状态与邻站不同<br />
                71 1方向电缆状态<br />
                72 提醒：1方向切换模式与邻站不同<br />
                110 提醒：2方向QHJ状态与邻站不同<br />
                111 2方向电缆状态<br />
                112 提醒：2方向切换模式与邻站不同<br />
                162 站间A通道或通信板故障（一方向A系）<br />
                164 站间B通道或通信板故障（一方向A系）<br />
                190 CPU板离线（一方向A系）<br />
                252 站间A通道或通信板故障（一方向B系）<br />
                254 站间B通道或通信板故障（一方向B系）<br />
                280 CPU板离线（一方向B系）<br />
                342 站间A通道或通信板故障（二方向A系）<br />
                344 站间B通道或通信板故障（二方向A系）<br />
                370 CPU板离线（二方向A系）<br />
                432 站间A通道或通信板故障（二方向B系）<br />
                434 站间B通道或通信板故障（二方向B系）<br />
                460 CPU板离线（二方向B系）<br />
              </p>
            </el-collapse-item>
            <el-collapse-item title="修改系统设置" name="2">
              <p>需要时，在厂家工程师指导下，在项目文件夹内打开文件：<br />
                /BT_NMS/backend/myproject/settings.py<br />
                修改设置。<br />
              </p>
            </el-collapse-item>
            <el-collapse-item title="其它" name="3">
              <p>如果您在使用中有任何问题，欢迎联系我们，我们的专业团队将竭诚为您服务！</p>
            </el-collapse-item>
          </el-collapse>
        </el-card>

        <el-card class="box-card">
          <template #header>
            <div class="clearfix">联系方式</div>
          </template>
          <p>如果您有任何问题，请通过以下方式联系我们：</p>
          <ul>
            <li>电子邮件: btserver001@163.com</li>
            <li>电话: 027-65522238</li>
          </ul>
        </el-card>
      </el-main>
    </el-container>
  </div>
  <div>
    <FileManageComponent />
  </div>
  <FooterComponent />
</template>

<script lang="ts" setup>
  import { ElContainer, ElHeader, ElMain, ElCard, ElCollapse, ElCollapseItem } from 'element-plus';
  import FooterComponent from '@/components/FooterComponent.vue';
  import FileManageComponent from '@/components/FileManageComponent.vue';
</script>

<style scoped>
.help-page {
  padding: 20px;
}
h1 {
  color: #2c3e50;
  text-align: center;
}
.box-card {
  margin-bottom: 20px;
}
.clearfix {
  font-size: 18px;
  font-weight: bold;
}
</style>