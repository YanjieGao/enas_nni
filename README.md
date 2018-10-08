 # enas_nni
This code is for running enas code on nni system.  
link:  https://github.com/Microsoft/nni  

link:  https://github.com/melodyguan/enas   
Paper: https://arxiv.org/abs/1802.03268  

Install:  
  1 Need to install nni system first.  
  link:https://github.com/Microsoft/nni You need to choose the dev-enas branch.  
  Use command:   
    pip3 install -v --user git+https://github.com/Microsoft/nni.git@dev-enas  
    source ~/.bashrc  
  
  For rnn arch search:
    2 Modify the codeDir at ~/nni/examples/trials/enas/ptb_config.yml.   
      
  For cnn arch search:
    macro search:  
      Modify the codeDir at  ~/nni/examples/trials/enas/cifar10_macro_config.yml.  
      
    micro search:
      Modify the codeDir at ~/nni/examples/trials/enas/cifar10_micro_config.yml.    
        
  3 Download the dataset:
  
  For rnn arch search:
    the dataset are at enas_nni/nni/examples/trials/enas/data/ptb
    
  For cnn arch search:  
    You need to download the cifar10 data at https://www.cs.toronto.edu/~kriz/cifar.html (python version).  
    And put data at  enas_nni/nni/examples/trials/enas/data and rename the cifar-10-batches-py as cifar10 .   
  
  4 
  Run the commond:
  
  micro_search:
    nnictl create --config ~/nni/examples/trials/enas/cifar10_micro_config.yml  
  
  ptb_search:
    nnictl create --config ~/nni/examples/trials/enas/ptb_config.yml  
  
  macro_search:
    nnictl create --config ~/nni/examples/trials/enas/cifar10_macro_config.yml  
  

