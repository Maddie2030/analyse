pipeline {
  agent any
  options {
    timestamps()
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '30'))
    timeout(time: 90, unit: 'MINUTES')
  }
  stages {
    stage('Checkout') { steps { checkout scm } }
    stage('Current release gates') {
      steps {
        sh 'bash scripts/validate-current-release.sh'
        sh 'bash scripts/run-regression-tests.sh --static'
      }
    }
    stage('Change matrix') {
      steps { sh 'bash scripts/ci/service-matrix.sh | tee .ci-components.txt' }
    }
    stage('Hybrid image build') {
      when { expression { return env.MREADER_CI_BUILD_IMAGES == '1' } }
      steps { sh 'bash scripts/hybrid/build-images.sh' }
    }
  }
  post {
    always { archiveArtifacts artifacts: 'test-results/**/*,.ci-components.txt', allowEmptyArchive: true }
  }
}
